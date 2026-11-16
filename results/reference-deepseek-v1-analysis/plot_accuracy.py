#!/usr/bin/env python3
"""Report-only layout amendment; reuse completed statistics, never bootstrap or call a model."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
BASE=Path(__file__).resolve().parent
for domain in ('arithmetic','coding'):
    report=json.loads((BASE/domain/'analysis.json').read_text());rows=report['arms']
    fig,ax=plt.subplots(figsize=(12,max(3.4,len(rows)*.85+1.2)))
    for i,row in enumerate(rows):
        ax.errorbar(row['accuracy']*100,i,xerr=[[100*(row['accuracy']-row['cluster95_low'])],[100*(row['cluster95_high']-row['accuracy'])]],fmt='o',color=('#0072B2','#D55E00','#009E73','#CC79A7')[i%4],capsize=4)
    ax.set(yticks=range(len(rows)),yticklabels=[r['arm']for r in rows],xlim=(-2,102),ylim=(-.5,len(rows)-.5),xlabel='Task/seed accuracy (%) with task-cluster empirical 95% interval');ax.invert_yaxis()
    ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Evaluation '+domain+' — fixed task scope',y=.97,fontsize=14)
    fig.text(.02,.02,'All-pass empirical intervals are not a true 100% correctness guarantee. TP4/native and single-replica recipes use different compute/reasoning.',fontsize=8)
    fig.subplots_adjust(left=.32,right=.98,top=.83,bottom=.22)
    for ext in ('png','svg'):fig.savefig(BASE/domain/('accuracy-cluster95.'+ext),dpi=200,bbox_inches='tight',pad_inches=.2)
    plt.close(fig)
