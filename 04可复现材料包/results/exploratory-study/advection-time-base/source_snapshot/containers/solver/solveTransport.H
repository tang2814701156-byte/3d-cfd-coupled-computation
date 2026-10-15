{
    const scalar now = runTime.value(), dt = runTime.deltaTValue();
    scalarField previousT(T.oldTime().primitiveField());
    scalarField previousA(alpha.oldTime().primitiveField());
    volScalarField sourceT(IOobject("sourceT", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE), mesh, dimensionedScalar("zero", dimTemperature/dimTime, 0));
    volScalarField sourceA(IOobject("sourceA", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE), mesh, dimensionedScalar("zero", dimless/dimTime, 0));
    if (manufactured)
    {
        const scalar decay = Foam::exp(-now/tau);
        forAll(T, i)
        {
            sourceT[i] = -(tInitial-tSupply)*decay/tau + U[i].z()*gt;
            sourceA[i] = -(aInitial-aSupply)*decay/tau + U[i].z()*ga;
        }
    }
    fvScalarMatrix TEqn(fvm::ddt(T) + fvm::div(phi,T) - fvm::laplacian(DT,T) == sourceT);
    fvScalarMatrix AEqn(fvm::ddt(alpha) + fvm::div(phi,alpha) - fvm::laplacian(DA,alpha) == sourceA);
    TEqn.solve(); AEqn.solve();
    // Do not clamp alpha: boundedness and conservation errors must remain observable.
    const surfaceScalarField fluxT(TEqn.flux()), fluxA(AEqn.flux());
    scalar storageT=0, storageA=0, srcT=0, srcA=0, errorT=0, errorA=0, volume=0;
    scalar momentumStorage=0, kineticStorage=0;
    forAll(T,i)
    {
        const scalar v=mesh.V()[i]; volume+=v;
        storageT += v*(T[i]-previousT[i]); storageA += v*(alpha[i]-previousA[i]);
        srcT += v*sourceT[i]*dt; srcA += v*sourceA[i]*dt;
        momentumStorage += rhoLedger*v*(U[i].z()-U.oldTime()[i].z());
        kineticStorage += 0.5*rhoLedger*v*(magSqr(U[i])-magSqr(U.oldTime()[i]));
        if (manufactured)
        {
            const scalar z=mesh.C()[i].z()-inletPosition;
            const scalar exactT=tSupply+(tInitial-tSupply)*Foam::exp(-now/tau)+gt*z;
            const scalar exactA=aSupply+(aInitial-aSupply)*Foam::exp(-now/tau)+ga*z;
            errorT += v*sqr(T[i]-exactT); errorA += v*sqr(alpha[i]-exactA);
        }
        else if (analyticAdvection)
        {
            // Characteristics of source-free advection by the analytic Poiseuille field.
            const vector c=mesh.C()[i];
            const scalar axial=Foam::max(c.z()-inletPosition, scalar(0));
            const scalar speed=2*referenceVelocity*(1-(sqr(c.x())+sqr(c.y()))/sqr(referenceRadius));
            const scalar age=speed>SMALL ? Foam::max(now-axial/speed, scalar(0)) : 0;
            const scalar exactT=tSupply+(tInitial-tSupply)*Foam::exp(-age/tau);
            const scalar exactA=aSupply+(aInitial-aSupply)*Foam::exp(-age/tau);
            errorT += v*sqr(T[i]-exactT); errorA += v*sqr(alpha[i]-exactA);
        }
    }
    scalar bt=0, ba=0, bm=0, mt=0, pressureImpulse=0, viscousImpulse=0;
    const volTensorField gradU(fvc::grad(U));
    const scalar nuLedger=laminarTransport.nu()().average().value();
    scalar kineticBoundary=0, pressureBoundary=0, viscousWork=0, viscousDissipation=0;
    forAll(U,i) viscousDissipation += 2*rhoLedger*nuLedger*mesh.V()[i]*magSqr(symm(gradU[i]))*dt;
    forAll(mesh.boundary(),patch)
    {
        const auto& f=phi.boundaryField()[patch];
        const auto& area=mesh.Sf().boundaryField()[patch];
        forAll(f,j)
        {
            const scalar mass=f[j]*rhoLedger*dt;
            bm+=mass;
            bt += (fluxT.boundaryField()[patch][j]-trefLedger*f[j])*rhoLedger*cpLedger*dt;
            ba += fluxA.boundaryField()[patch][j]*rhoLedger*dt;
            mt += mass*U.boundaryField()[patch][j].z();
            pressureImpulse -= rhoLedger*p.boundaryField()[patch][j]*area[j].z()*dt;
            viscousImpulse += rhoLedger*nuLedger*((2*symm(gradU.boundaryField()[patch][j])) & area[j]).z()*dt;
            kineticBoundary += 0.5*mass*magSqr(U.boundaryField()[patch][j]);
            pressureBoundary += rhoLedger*p.boundaryField()[patch][j]*f[j]*dt;
            viscousWork += rhoLedger*nuLedger*(U.boundaryField()[patch][j] & ((2*symm(gradU.boundaryField()[patch][j])) & area[j]))*dt;
        }
    }
    const label inlet=mesh.boundaryMesh().findPatchID("inlet");
    scalar tin=0, ain=0, mdot=0, thermalIn=0, phaseIn=0, inletMomentum=0, inletPressure=0;
    scalar inletKinetic=0, inletWork=0;
    forAll(phi.boundaryField()[inlet],j)
    {
        const scalar mass=-rhoLedger*phi.boundaryField()[inlet][j]; mdot+=mass;
        tin+=mass*T.boundaryField()[inlet][j]; ain+=mass*alpha.boundaryField()[inlet][j];
        thermalIn-=rhoLedger*cpLedger*dt*(fluxT.boundaryField()[inlet][j]-trefLedger*phi.boundaryField()[inlet][j]);
        phaseIn-=rhoLedger*dt*fluxA.boundaryField()[inlet][j];
        inletMomentum+=mass*U.boundaryField()[inlet][j].z()*dt;
        inletPressure-=rhoLedger*p.boundaryField()[inlet][j]*mesh.Sf().boundaryField()[inlet][j].z()*dt;
        inletKinetic+=0.5*mass*magSqr(U.boundaryField()[inlet][j])*dt;
        inletWork+=mass*p.boundaryField()[inlet][j]*dt;
    }
    storageT*=rhoLedger*cpLedger; storageA*=rhoLedger; srcT*=rhoLedger*cpLedger; srcA*=rhoLedger;
    const scalar mechanicalResidual=kineticStorage+kineticBoundary+pressureBoundary-viscousWork+viscousDissipation;
    ledger << now << ',' << dt << ',' << volume << ',' << bm << ',' << storageT << ',' << bt << ',' << srcT << ',' << storageT+bt-srcT
        << ',' << storageA << ',' << ba << ',' << srcA << ',' << storageA+ba-srcA
        << ',' << Foam::sqrt(errorT/volume) << ',' << Foam::sqrt(errorA/volume) << ',' << tin/mdot << ',' << ain/mdot << ',' << mdot
        << ',' << thermalIn << ',' << phaseIn << ',' << momentumStorage << ',' << mt << ',' << pressureImpulse << ',' << viscousImpulse
        << ',' << momentumStorage+mt-pressureImpulse-viscousImpulse << ',' << gMin(alpha.primitiveField()) << ',' << gMax(alpha.primitiveField())
        << ',' << inletMomentum << ',' << inletPressure << ',' << kineticStorage << ',' << kineticBoundary << ',' << pressureBoundary
        << ',' << viscousWork << ',' << viscousDissipation << ',' << mechanicalResidual << ',' << mechanicalResidual+storageT+bt-srcT
        << ',' << inletKinetic << ',' << inletWork << '\n';
    ledger.flush();
}
