"""Independent fully-developed unsteady Stokes reference coupled to pipe inertia.

Cell-centred radial finite volumes and exact matrix exponentials between valve
events. This reference relaxes the fixed parabolic inlet constraint of the 3-D
case; its discrepancy measures model sensitivity, not an exact 3-D error.
"""
import numpy as np


def radial_operator(radius, nu, cells):
    faces = np.linspace(0., radius, cells+1)
    centers = (faces[:-1]+faces[1:])/2
    volumes = (faces[1:]**2-faces[:-1]**2)/2
    matrix = np.zeros((cells, cells))
    for i in range(cells-1):
        flux = nu*faces[i+1]/(centers[i+1]-centers[i])
        matrix[i, i] -= flux/volumes[i]; matrix[i, i+1] += flux/volumes[i]
        matrix[i+1, i] += flux/volumes[i+1]; matrix[i+1, i+1] -= flux/volumes[i+1]
    matrix[-1, -1] -= nu*radius/(radius-centers[-1])/volumes[-1]
    return matrix, volumes/volumes.sum(), faces


def reference(case, times, cells=64):
    p = case['pipe']; length3 = case['cfd']['length']
    diffusion, weights, faces = radial_operator(p['radius'],p['nu'],cells)
    state = 2*p['velocity']*(1-(faces[:-1]**2+faces[1:]**2)/(2*p['radius']**2))
    opening = p.get('opening',1.)
    events = iter(case['control']['events']); event = next(events,None)
    previous = 0.; output = []; cache = {}
    def operator(a):
        if a not in cache:
            resistance = 8*p['rho']*p['nu']*p['length']/p['radius']**2+p['valve_resistance']*(a**-2-1)
            row = (resistance/p['rho']*weights+p['length']*weights@diffusion)/(p['length']+length3)
            matrix = diffusion-np.outer(np.ones(cells),row)
            forcing = np.full(cells,p['supply_pressure']/(p['rho']*(p['length']+length3)))
            eigen, vectors = np.linalg.eig(matrix)
            steady = np.linalg.solve(matrix,-forcing)
            cache[a] = row, eigen, vectors, np.linalg.inv(vectors), steady
        return cache[a]
    def advance(state, dt, a):
        _, eig, vec, inv, steady = operator(a)
        return np.real_if_close(steady+vec@(np.exp(eig*dt)*(inv@(state-steady)))).real
    for target in times:
        while event and event['time_s'] < target-1e-12:
            state = advance(state,event['time_s']-previous,opening)
            previous = event['time_s']; opening = event['opening']; event = next(events,None)
        state = advance(state,target-previous,opening); previous = target
        row = operator(opening)[0]
        gradient = p['supply_pressure']/(p['rho']*(p['length']+length3))-row@state
        output.append([target,float(weights@state),float(p['rho']*length3*gradient)])
    return np.array(output)
