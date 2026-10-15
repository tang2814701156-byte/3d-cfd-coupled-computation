FROM public.ecr.aws/docker/library/ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
COPY .build/ca-bundle.pem /opt/cfd-ca-bundle.pem
ENV SSL_CERT_FILE=/opt/cfd-ca-bundle.pem CURL_CA_BUNDLE=/opt/cfd-ca-bundle.pem
RUN printf 'Acquire::https::CaInfo "/opt/cfd-ca-bundle.pem";\nAcquire::Retries "3";\n' > /etc/apt/apt.conf.d/80cfd-network \
    && sed -i 's|http:|https:|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg build-essential pkg-config python3-dev python3-venv unzip
RUN curl --fail --retry 3 https://dl.openfoam.com/pubkey.gpg -o /tmp/openfoam-key \
    && gpg --dearmor < /tmp/openfoam-key > /usr/share/keyrings/openfoam.gpg \
    && printf 'deb [arch=amd64 signed-by=/usr/share/keyrings/openfoam.gpg] https://dl.openfoam.com/repos/deb noble main\n' > /etc/apt/sources.list.d/openfoam.list \
    && apt-get update && apt-get install -y --no-install-recommends openfoam2512-dev \
    && rm /tmp/openfoam-key
COPY .build/libprecice3_3.4.1_noble.deb /tmp/libprecice.deb
RUN apt-get install -y --no-install-recommends /tmp/libprecice.deb && rm /tmp/libprecice.deb
COPY requirements.txt /opt/cfd/requirements.txt
RUN python3 -m venv /opt/cfd/venv \
    && /opt/cfd/venv/bin/pip install --no-cache-dir -r /opt/cfd/requirements.txt
ENV PATH=/opt/cfd/venv/bin:$PATH WM_NCOMPPROCS=4
COPY .build/openfoam-adapter /opt/cfd/openfoam-adapter
RUN source /usr/lib/openfoam/openfoam2512/etc/bashrc \
    && cd /opt/cfd/openfoam-adapter && chmod +x Allwmake && ./Allwmake \
    && cp "$FOAM_USER_LIBBIN/libpreciceAdapterFunctionObject.so" /opt/cfd/ \
    && precice-version
COPY containers/entrypoint.sh /opt/cfd/entrypoint.sh
RUN chmod +x /opt/cfd/entrypoint.sh
ENV LD_LIBRARY_PATH=/opt/cfd
WORKDIR /work
ENTRYPOINT ["/opt/cfd/entrypoint.sh"]

