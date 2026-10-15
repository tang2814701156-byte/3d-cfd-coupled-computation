"""Prepare fixed upstream inputs and the public CA bundle for the Docker build."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import ssl
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=90) as response, target.open("wb") as output:
        while data := response.read(1024 * 1024):
            output.write(data)


def prepare() -> None:
    BUILD.mkdir(exist_ok=True)
    ca = ssl.create_default_context().get_ca_certs(binary_form=True)
    (BUILD / "ca-bundle.pem").write_text(
        "".join(ssl.DER_cert_to_PEM_cert(cert) for cert in ca), encoding="ascii"
    )
    name = "libprecice3_3.4.1_noble.deb"
    base = "https://github.com/precice/precice/releases/download/v3.4.1/"
    checksum_path = BUILD / (name + ".sha256")
    if not checksum_path.exists():
        download(base + checksum_path.name, checksum_path)
    expected = checksum_path.read_text().split()[0]
    package = BUILD / name
    if not package.exists() or hashlib.sha256(package.read_bytes()).hexdigest() != expected:
        download(base + name, package)
    assert hashlib.sha256(package.read_bytes()).hexdigest() == expected, "preCICE checksum mismatch"

    archive = next((ROOT / "docs/references/code").glob("openfoam-adapter-*.zip"))
    destination = BUILD / "openfoam-adapter"
    with zipfile.ZipFile(archive) as source:
        prefix = source.namelist()[0].split("/")[0] + "/"
        for member in source.infolist():
            relative = Path(member.filename.removeprefix(prefix))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe source archive path")
            if not relative.parts or member.is_dir():
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(member))
    # ZIP extraction on Windows loses Unix executable bits; Docker restores them.
    patch_adapter(destination)
    (BUILD / "sources.json").write_text(json.dumps({
        "precice": "3.4.1", "precice_deb_sha256": expected,
        "adapter_archive": archive.name,
        "adapter_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "instrumentation": "scripts/prepare.py:patch_adapter",
    }, indent=2), encoding="utf-8")
    print("Prepared verified preCICE package and instrumented adapter.")


def patch_adapter(destination: Path) -> None:
    """Instrument the real read/apply and write paths, using one Linux monotonic clock."""
    p = destination / "Adapter.C"
    s = p.read_text(encoding="utf-8")
    header = '''
#include <fstream>
#include <sstream>
#include <cstdlib>
#include <cstdio>
#include <ctime>
namespace {
long long cfdNowNs() {
    timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return static_cast<long long>(t.tv_sec)*1000000000LL + t.tv_nsec;
}
void cfdTraceRead(double t, double relative) {
    const char* root = std::getenv("CFD_TRACE_DIR"); if (!root) return;
    long long seq=0, sent=0; double target=0;
    std::ifstream source(std::string(root)+"/forward.stamp");
    if (!(source >> seq >> target >> sent)) return;
    std::ofstream out(std::string(root)+"/foam_reads.csv", std::ios::app);
    out.precision(17);
    out << seq << ',' << target << ',' << sent << ',' << cfdNowNs()
        << ',' << t << ',' << relative << '\\n';
}
void cfdTraceWrite(double t, long long sent) {
    const char* root = std::getenv("CFD_TRACE_DIR"); if (!root) return;
    static long long seq=0; ++seq;
    std::string file=std::string(root)+"/reverse.stamp";
    std::ofstream out(file+".tmp"); out.precision(17);
    out << seq << ' ' << t << ' ' << sent << '\\n'; out.close();
    std::rename((file+".tmp").c_str(), file.c_str());
}
}
'''
    read_marker = "    ACCUMULATE_TIMER(timeInRead_);"
    write_marker = "    ACCUMULATE_TIMER(timeInWrite_);"
    assert s.count(read_marker) == 1 and s.count(write_marker) == 1
    s = header + s.replace(read_marker, "    cfdTraceRead(runTime_.value(), relativeReadTime);\n" + read_marker)
    write_start = "void preciceAdapter::Adapter::writeCouplingData()\n{\n    SETUP_TIMER();"
    assert s.count(write_start) == 1
    s = s.replace(write_start, write_start + "\n    const long long cfdSentNs = cfdNowNs();")
    s = s.replace(write_marker, "    cfdTraceWrite(runTime_.value(), cfdSentNs);\n" + write_marker)
    p.write_text(s, encoding="utf-8")

    # Normalize the discrete parabolic profile to the prescribed circular-pipe flow.
    # This patch is restricted to this project's serial, z-axis circular inlet case.
    velocity = destination / "FF/Velocity.C"
    s = velocity.read_text(encoding="utf-8")
    marker = "        }\n    }\n}\n\nbool preciceAdapter::FF::Velocity::isLocationTypeSupported"
    assert s.count(marker) == 1
    addition = '''
        const char* radiusEnv = std::getenv("CFD_RADIUS");
        if (radiusEnv && dim == 3) {
            const double radius = std::atof(radiusEnv);
            const auto& areas = U_->mesh().magSf().boundaryField()[patchID];
            const auto& centers = U_->mesh().Cf().boundaryField()[patchID];
            double weightedBulk=0.0, weights=0.0, flow=0.0;
            forAll(valuePatch, i) {
                const double factor=2.0*(1.0-(sqr(centers[i].x())+sqr(centers[i].y()))/sqr(radius));
                if (factor > 1e-8) {
                    weightedBulk += areas[i]*valuePatch[i].z()/factor;
                    weights += areas[i];
                }
                flow += areas[i]*valuePatch[i].z();
            }
            const double bulk=weightedBulk/weights;
            const double target=3.14159265358979323846*radius*radius*bulk;
            if (std::abs(flow)>1e-20) valuePatch *= target/flow;
            double actual=0.0;
            forAll(valuePatch,i) actual += areas[i]*valuePatch[i].z();
            const char* trace = std::getenv("CFD_TRACE_DIR");
            if (trace) {
                std::ofstream out(std::string(trace)+"/foam_boundary.csv",std::ios::app);
                out.precision(17);
                out << U_->mesh().time().value() << ',' << U_->mesh().time().deltaTValue()
                    << ',' << bulk << ',' << target << ',' << actual << ','
                    << actual-target << '\\n';
            }
        }
'''
    s = '#include <fstream>\n#include <cstdlib>\n#include <cmath>\n' + s
    s = s.replace(marker, "        }\n" + addition + "    }\n}\n\nbool preciceAdapter::FF::Velocity::isLocationTypeSupported")
    velocity.write_text(s, encoding="utf-8")

    # Project pressure by area, so the 1D pressure represents the integrated face force.
    pressure = destination / "FF/Pressure.C"
    s = pressure.read_text(encoding="utf-8")
    marker = "    return bufferIndex;"
    assert s.count(marker) == 1
    weighted = '''
    if (std::getenv("CFD_RADIUS") && patchIDs_.size()==1
        && this->locationType_ == LocationType::faceCenters) {
        const int id=patchIDs_.at(0);
        const auto& areas=p_->mesh().magSf().boundaryField()[id];
        const auto& values=p_->boundaryField()[id];
        double sum=0.0, area=0.0;
        forAll(values,i) { sum+=values[i]*areas[i]; area+=areas[i]; }
        const double mean=sum/area;
        for (int i=0;i<bufferIndex;++i) buffer[i]=mean;
    }
'''
    pressure.write_text('#include <cstdlib>\n' + s.replace(marker, weighted + marker), encoding="utf-8")


if __name__ == "__main__":
    prepare()
