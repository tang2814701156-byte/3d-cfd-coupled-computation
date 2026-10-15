"""Render QA pages with the canonical renderer using background Word COM PDFs."""
import argparse
import importlib.util
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--renderer',type=Path,required=True)
args=parser.parse_args()
spec=importlib.util.spec_from_file_location('docx_renderer',args.renderer)
renderer=importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
root=Path(__file__).resolve().parents[1]
qa=root/'delete/20261013-hardening/word-qa'
def word_pdf(doc_path,user_profile,convert_tmp_dir,stem,verbose):
    pdf=qa/(stem+'.pdf')
    if not pdf.is_file(): raise FileNotFoundError(pdf)
    return str(pdf),'PDF exported by background Word COM'
renderer.convert_to_pdf=word_pdf
for name,folder in [('一三维耦合方案说明_技术补强版','scheme'),('一三维双向耦合算例验证报告_技术补强版','report')]:
    sys.argv=[str(args.renderer),str(root/'docs'/(name+'.docx')),'--output_dir',str(qa/folder),'--dpi','110']
    renderer.main()
