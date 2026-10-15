"""Render longitudinal field slices from saved OpenFOAM results with pvpython.

Usage: pvpython --force-offscreen-rendering scripts/export_paraview_fields.py
--results results --output results/document-figures/word-report
All panels use y=0, inlet on the left and outlet on the right. Pressure is
converted from kinematic pressure to Pa using each case's density. Absolute
temperature error is evaluated at cell centres before display interpolation.
"""
from pathlib import Path
import argparse,json,builtins
from paraview.simple import *
from paraview import servermanager
from paraview.simple import _DisableFirstRenderCameraReset
from vtkmodules.util.numpy_support import vtk_to_numpy
import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('--results',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
records={};case_slice_cache={}
_DisableFirstRenderCameraReset()

def blocks(data):
    if data.IsA('vtkMultiBlockDataSet'):
        for i in range(data.GetNumberOfBlocks()):
            if data.GetBlock(i):yield from blocks(data.GetBlock(i))
    elif data.IsA('vtkDataSet'):yield data

def load_case_slice(name):
    if name in case_slice_cache:return case_slice_cache[name]
    root=args.results/name;case=json.loads((root/'case.json').read_text(encoding='utf-8'))
    marker=root/'fluid3d/case.foam'
    if not marker.exists():raise FileNotFoundError(marker)
    r=OpenFOAMReader(FileName=str(marker.resolve()));r.MeshRegions=['internalMesh'];r.CellArrays=['U','p','T','alpha']
    r.UpdatePipelineInformation();time=float(case['coupling']['end_time_s'])
    assert any(abs(float(t)-time)<1e-10 for t in r.TimestepValues),(name,r.TimestepValues,time)
    r.UpdatePipeline(time)
    prog=ProgrammableFilter(Input=r)
    pipe=case['pipe'];trans=case.get('transport',{})
    prog.Script=f'''import numpy as np
from vtkmodules.vtkFiltersCore import vtkCellCenters
from vtkmodules.util.numpy_support import vtk_to_numpy,numpy_to_vtk
def visit(src,dst):
    if src.IsA('vtkMultiBlockDataSet'):
        for i in range(src.GetNumberOfBlocks()):
            if src.GetBlock(i):visit(src.GetBlock(i),dst.GetBlock(i))
        return
    def add(name,values):
        a=numpy_to_vtk(values,deep=True);a.SetName(name);dst.GetCellData().AddArray(a)
    cd=src.GetCellData()
    add('PressurePa',vtk_to_numpy(cd.GetArray('p'))*{pipe['rho']})
    if cd.GetArray('T') and {bool(case.get('scalar_cfd',{}).get('analytic_advection',False))}:
        centres=vtkCellCenters();centres.SetInputData(src);centres.Update()
        xyz=vtk_to_numpy(centres.GetOutput().GetPoints().GetData())
        velocity=2*{pipe['velocity']}*(1-(xyz[:,0]**2+xyz[:,1]**2)/{pipe['radius']}**2)
        travel=(xyz[:,2]-{pipe['length']})/np.maximum(velocity,1e-15)
        tau={trans.get('volume_m3',1)}/(np.pi*{pipe['radius']}**2*{pipe['velocity']})
        ref={trans.get('supply_temperature_k',320)}+({trans.get('temperature_k',300)}-{trans.get('supply_temperature_k',320)})*np.exp(-np.maximum(0,{time}-travel)/tau)
        add('TemperatureReference',ref)
        add('TemperatureAbsError',np.abs(vtk_to_numpy(cd.GetArray('T'))-ref))
src=self.GetInputDataObject(0,0);dst=self.GetOutputDataObject(0)
dst.ShallowCopy(src);visit(src,dst)
'''
    prog.UpdatePipeline(time)
    data=servermanager.Fetch(prog);stats={}
    for namefield in ['U','PressurePa','T','alpha','TemperatureAbsError']:
        arrays=[vtk_to_numpy(b.GetCellData().GetArray(namefield)) for b in blocks(data) if b.GetCellData().GetArray(namefield)]
        if arrays:
            a=np.concatenate(arrays)
            if a.ndim==2:a=np.linalg.norm(a,axis=1)
            stats[namefield]={'min':float(a.min()),'max':float(a.max())}
    records[name]={'time_s':time,'cell_count':builtins.sum(b.GetNumberOfCells() for b in blocks(data)),'cell_ranges':stats}
    smooth=CellDatatoPointData(Input=prog);smooth.UpdatePipeline(time)
    cut=Slice(Input=smooth);cut.SliceType='Plane';cut.SliceType.Origin=[0,0,.03];cut.SliceType.Normal=[0,1,0];cut.UpdatePipeline(time)
    case_slice_cache[name]=(cut,time);return cut,time

def panel(v,name,field,title,limits):
    s,t=load_case_slice(name);v.ViewTime=t;v.UseColorPaletteForBackground=0;v.Background=[1,1,1]
    v.OrientationAxesVisibility=0;v.CameraParallelProjection=1
    d=Show(s,v);d.Representation='Surface';d.Ambient=1;d.Diffuse=0
    ColorBy(d,('POINTS',field,'Magnitude') if field=='U' else ('POINTS',field))
    lut=GetColorTransferFunction(field);lut.ColorSpace='RGB'
    lut.RGBPoints=[0,.267,.005,.329,.25,.230,.322,.546,.5,.128,.567,.551,.75,.369,.789,.383,1,.993,.906,.144]
    lut.RescaleTransferFunction(*limits)
    lut.AutomaticRescaleRangeMode='Never';d.SetScalarBarVisibility(v,True)
    bar=GetScalarBar(lut,v);bar.Orientation='Horizontal';bar.WindowLocation='Any Location'
    wide=int(v.ViewSize[0])>1500
    bar.Position=[.34 if wide else .18,.075];bar.ScalarBarLength=.32 if wide else .64;bar.ScalarBarThickness=22
    bar.Title='';bar.ComponentTitle='';bar.LabelColor=[.12,.12,.12];bar.LabelFontFamily='Times';bar.LabelFontSize=42
    bar.RangeLabelFormat='{:.4g}';bar.LabelFormat='{:.4g}';bar.AutomaticLabelFormat=0
    bar.UseCustomLabels=1;bar.CustomLabels=list(np.linspace(*limits,5));bar.DrawTickLabels=1
    label=Text();label.Text=title;ld=Show(label,v);ld.WindowLocation='Upper Center';ld.FontFamily='Times';ld.FontSize=46;ld.Color=[.12,.12,.12]
    v.CameraPosition=[0,.1,.03];v.CameraFocalPoint=[0,0,.03];v.CameraViewUp=[1,0,0];v.CameraParallelScale=.0088
    Render(v)

def figure(filename,panels,cols=2):
    layout=CreateLayout(name=filename)
    if len(panels)==2:
        layout.SplitHorizontal(0,.5);ids=[1,2];size=[2200,850]
    elif len(panels)==3:
        layout.SplitVertical(0,.5);layout.SplitHorizontal(1,.5);ids=[3,4,2];size=[2200,1700]
    else:
        layout.SplitHorizontal(0,.5);layout.SplitVertical(1,.5);layout.SplitVertical(2,.5);ids=[3,5,4,6];size=[2200,1700]
    views=[]
    for slot,values in zip(ids,panels):
        v=CreateView('RenderView');AssignViewToLayout(v,layout,hint=slot);views.append(v)
    layout.SetSize(*size)
    for v,values in zip(views,panels):panel(v,*values)
    SaveScreenshot(str(args.output/filename),layout,ImageResolution=size)
    for v in views:Delete(v)
    Delete(layout)

figure('steady-field-contours.png',[
    ('verification/steady-fine','U','(a) Velocity magnitude (m/s)',(0,.2)),
    ('verification/steady-fine','PressurePa','(b) Pressure (Pa)',(0,7))])
figure('advection-field-contours.png',[
    ('verification/advection-fine','T','(a) Temperature (K)',(300,314)),
    ('verification/advection-fine','alpha','(b) Phase A volume fraction',(0.2,.62))])
figure('valve-field-contours.png',[
    ('verification/valve-0.001','U','(a) Velocity magnitude (m/s)',(0,.2)),
    ('verification/valve-0.001','PressurePa','(b) Pressure (Pa)',(0,7)),
    ('verification/valve-0.001','T','(c) Temperature (K)',(300,314)),
    ('verification/valve-0.001','alpha','(d) Phase A volume fraction',(.2,.62))])
figure('refinement-error-contours.png',[
    ('verification/advection','TemperatureAbsError','(a) 6/40, 0.5 ms; error (K)',(0,3)),
    ('exploratory-study/advection-time-quarter','TemperatureAbsError','(b) 6/40, 0.125 ms; error (K)',(0,3)),
    ('exploratory-study/advection-space-fine','TemperatureAbsError','(c) 8/80, 0.5 ms; error (K)',(0,3))])
figure('combined-error-contours.png',[
    ('exploratory-study/advection-space-fine','TemperatureAbsError','(a) 8/80, 0.5 ms; error (K)',(0,3)),
    ('hardening-study/advection-combined','TemperatureAbsError','(b) 8/80, 0.125 ms; error (K)',(0,3))])
(args.output/'field-contours-provenance.json').write_text(json.dumps({'plane':'y = 0','view':'z increasing left to right from 20 to 40 mm','display':'cell to point interpolation after cell-centre error evaluation','cases':records},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(records))
