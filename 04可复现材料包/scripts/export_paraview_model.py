"""Export actual OpenFOAM geometry and mesh with ParaView pvpython.

Run with pvpython --force-offscreen-rendering export_paraview_model.py
--case-file /path/to/model.foam --output /path/to/figures.
The .foam marker must be beside the case's 0, constant and system directories.
"""
from pathlib import Path
import argparse,json
from paraview.simple import *

parser=argparse.ArgumentParser()
parser.add_argument('--case-file',required=True,type=Path)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)

def reader(region):
    r=OpenFOAMReader(FileName=str(args.case_file.resolve()))
    r.MeshRegions=[region];r.CellArrays=[];r.UpdatePipeline()
    t=Transform(Input=r);t.Transform.Scale=[1000,1000,1000];t.UpdatePipeline()
    return r,t

def view():
    v=CreateView('RenderView');v.ViewSize=[2200,1050]
    v.UseColorPaletteForBackground=0;v.Background=[1,1,1]
    v.OrientationAxesVisibility=0;v.CameraParallelProjection=1
    return v

def label(v,txt,pos,color=(.12,.15,.18),size=24):
    s=Text();s.Text=txt;d=Show(s,v)
    d.WindowLocation='Any Location';d.Position=pos;d.FontFamily='Times'
    d.FontSize=size;d.Color=color
    return s

colors={'patch/fixedWalls':[.32,.57,.72],'patch/inlet':[.90,.47,.18],'patch/outlet':[.26,.63,.45]}
sources={k:reader(k) for k in colors}
check=OpenFOAMReader(FileName=str(args.case_file.resolve()))
check.MeshRegions=['internalMesh'];check.CellArrays=[];check.UpdatePipeline()
assert check.GetDataInformation().GetNumberOfCells()==7200

geo=view()
for k,(raw,t) in sources.items():
    smooth=SurfaceNormals(Input=ExtractSurface(Input=t));smooth.FeatureAngle=180
    d=Show(smooth,geo);d.Representation='Surface';d.ColorArrayName=['POINTS','']
    d.DiffuseColor=colors[k];d.AmbientColor=colors[k]
    d.Opacity=.64 if k.endswith('fixedWalls') else .9
    d.Ambient=.35;d.Diffuse=.65;d.Specular=.35;d.SpecularPower=30
    d.Interpolation='Gouraud'
geo.ResetCamera()
geo.CameraPosition=[35,-12,8];geo.CameraFocalPoint=[0,0,30]
geo.CameraViewUp=[-12,-35,0];geo.CameraParallelScale=7.2
geo.ViewSize=[2200,1100]
Render(geo)
SaveScreenshot(str(args.output/'model-domain-paraview-raw.png'),geo,ImageResolution=[2200,1100])

left=view();right=view()
layout=CreateLayout(name='Model mesh')
AssignViewToLayout(left,layout,hint=0);layout.SplitHorizontal(0,.6);AssignViewToLayout(right,layout,hint=2)
for k,(raw,t) in sources.items():
    d=Show(t,left);d.Representation='Surface With Edges';d.ColorArrayName=['POINTS','']
    d.DiffuseColor=[.79,.87,.92];d.AmbientColor=[.79,.87,.92]
    d.EdgeColor=[.22,.32,.39];d.LineWidth=.7;d.Opacity=1
    d.Ambient=.55;d.Diffuse=.45;d.Specular=0
left.ResetCamera();left.CameraPosition=[32,-50,63];left.CameraFocalPoint=[0,0,30]
left.CameraViewUp=[0,-1,0];left.CameraParallelScale=12.0
d=Show(sources['patch/inlet'][1],right);d.Representation='Surface With Edges';d.ColorArrayName=['POINTS','']
d.DiffuseColor=[.88,.93,.96];d.AmbientColor=[.88,.93,.96];d.EdgeColor=[.22,.32,.39];d.LineWidth=1.0;d.Ambient=1;d.Diffuse=0
right.ResetCamera();right.CameraPosition=[0,0,-50];right.CameraFocalPoint=[0,0,20]
right.CameraViewUp=[0,1,0];right.CameraParallelScale=6.1
layout.SetSize(2200,1000)
Render(left);Render(right)
SaveScreenshot(str(args.output/'model-mesh-paraview.png'),layout,ImageResolution=[2200,1000])
print(json.dumps({'software':'ParaView','cells':7200,'source':str(args.case_file),'images':['model-domain-paraview-raw.png','model-mesh-paraview.png']}))

