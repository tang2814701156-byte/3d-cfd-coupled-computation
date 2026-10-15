"""Compose annotated scientific figures from the unmodified ParaView render.

First run export_paraview_model.py with pvpython. Then run this script with
Python and the project's numpy/matplotlib dependencies. Only white margins are
cropped; the model's geometry and mesh are unchanged.
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/document-figures/word-report'
plt.rcParams.update({'font.family':['Times New Roman','SimSun','DejaVu Serif'],
                     'axes.unicode_minus':False,'font.size':13})
BLUE='#286781';ORANGE='#A96231';GREEN='#31755D';GRAY='#4B555F'
raw=plt.imread(OUT/'model-domain-paraview-raw.png')
mask=raw[:,:,:3].min(axis=2)<.94
yy,xx=np.where(mask)
raw=raw[max(0,yy.min()-8):yy.max()+9,max(0,xx.min()-8):xx.max()+9]

def canvas(w=11,h=5.5):
    fig,ax=plt.subplots(figsize=(w,h))
    fig.subplots_adjust(0,0,1,1);ax.set_xlim(0,w);ax.set_ylim(0,h);ax.axis('off')
    return fig,ax

def dim(ax,a,b,y,label,color=GRAY):
    ax.annotate('',xy=(b,y),xytext=(a,y),arrowprops=dict(arrowstyle='<->',color=color,lw=1))
    ax.text((a+b)/2,y+.13,label,ha='center',va='bottom',color=color,fontsize=13)
    for x in [a,b]:ax.plot([x,x],[y-.12,y+.42],lw=.8,color=color)

def leader(ax,text,xy,xytext,color):
    ax.annotate(text,xy=xy,xytext=xytext,ha='center',va='bottom',fontsize=14,
                color=color,linespacing=1.6,arrowprops=dict(arrowstyle='-',color=color,lw=1.1,connectionstyle='angle,angleA=90,angleB=0,rad=0'))

fig,ax=canvas()
ax.imshow(raw,extent=[2.0,8.7,1.45,4.45],aspect='auto',zorder=1)
leader(ax,'耦合入口\n速度、温度与相分数',xy=(2.74,3.54),xytext=(1.65,4.68),color=ORANGE)
leader(ax,'刚性管壁\n无滑移条件',xy=(5.6,4.18),xytext=(5.5,4.68),color=BLUE)
leader(ax,'远端出口\n表压 0 Pa',xy=(8.02,3.54),xytext=(8.55,4.68),color=GREEN)
ax.text(5.4,3.1,'三维圆管流体域',ha='center',color='white',fontsize=17)
ax.annotate('',xy=(6.7,2.7),xytext=(4.1,2.7),arrowprops=dict(arrowstyle='->',lw=1.8,color='white'))
ax.text(5.4,2.37,'流动方向',ha='center',color='white',fontsize=12)
dim(ax,2.74,8.02,.85,'轴向长度 20 mm')
ax.annotate('',xy=(9.2,4.4),xytext=(9.2,1.5),arrowprops=dict(arrowstyle='<->',lw=1,color=GRAY))
ax.text(9.38,2.95,'面积等效\n直径 10 mm',ha='left',va='center',color=GRAY,fontsize=13,linespacing=1.7)
ax.text(5.4,.22,'计算域位置：轴向 20–40 mm',ha='center',color=GRAY,fontsize=12)
fig.savefig(OUT/'model-domain-paraview.png',dpi=260);plt.close(fig)

fig,ax=canvas(11,4.4)
# One-dimensional equivalent is drawn as a centerline. The 3D portion uses
# the same ParaView screenshot as the detailed geometry figure.
ax.plot([.9,5.0],[2.30,2.30],color=ORANGE,lw=3,zorder=3)
ax.scatter([.9],[2.30],s=40,color=ORANGE,zorder=4)
ax.imshow(raw,extent=[4.4,9.8,1.08,3.5],aspect='auto',zorder=1)
ax.plot([5.0,5.0],[.95,3.7],ls=(0,(4,3)),color=ORANGE,lw=1.2,zorder=4)
ax.text(2.7,3.76,'一维等效管段',ha='center',color=ORANGE,fontsize=17)
ax.text(7.5,3.76,'三维圆管流体域',ha='center',color=BLUE,fontsize=17)
ax.text(2.7,2.72,'截面平均流量与混合状态',ha='center',color=GRAY,fontsize=12)
ax.annotate('',xy=(3.8,2.30),xytext=(2,2.30),arrowprops=dict(arrowstyle='->',lw=2,color=ORANGE))
ax.text(.9,1.7,'上游供压',ha='center',color=GRAY,fontsize=12)
ax.text(5,.63,'耦合截面',ha='center',color=ORANGE,fontsize=12)
dim(ax,.9,5,.3,'20 mm')
dim(ax,5,9.2,.3,'20 mm')
ax.text(7.3,2.33,'局部速度、压力与标量分布',ha='center',color='white',fontsize=12)
fig.savefig(OUT/'model-geometry.png',dpi=260);plt.close(fig)
print('Composed geometry and partition figures')
