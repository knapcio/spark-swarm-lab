#!/usr/bin/env python3
"""Render one explicitly supplied lineage JSON as a DAG; matplotlib imports only on render."""
import argparse
from collections import defaultdict
import heapq
import json
import math
from pathlib import Path

STYLES={'parent':('#0072B2','-'),'own_previous_program':('#4B5563','-'),
        'reviewer':('#E69F00','-'),'review_target':('#8A6B00','--'),
        'review_guidance':('#CC79A7','--'),'review_source':('#E69F00','--')}

def layout(document):
    """Longest-path levels from every edge; stable input order breaks same-level ties."""
    nodes=document['nodes'];edges=document['edges'];order={n['id']:i for i,n in enumerate(nodes)}
    if not nodes or len(order)!=len(nodes) or any(type(n['id'])is not str or not n['id']for n in nodes):
        raise ValueError('Nodes need unique nonempty string IDs')
    children=defaultdict(set);degree={name:0 for name in order};levels=dict.fromkeys(order,0)
    for edge in edges:
        a,b=edge['source'],edge['target']
        if a not in order or b not in order:raise ValueError('Dangling lineage edge')
        if b not in children[a]:children[a].add(b);degree[b]+=1
    ready=[(order[n],n)for n,d in degree.items()if d==0];heapq.heapify(ready);visited=[]
    while ready:
        _,name=heapq.heappop(ready);visited.append(name)
        for child in sorted(children[name],key=order.get):
            levels[child]=max(levels[child],levels[name]+1);degree[child]-=1
            if degree[child]==0:heapq.heappush(ready,(order[child],child))
    if len(visited)!=len(nodes):raise ValueError('Lineage contains a cycle')
    columns=defaultdict(list)
    for name in visited:columns[levels[name]].append(name)
    positions={name:(level*3.8,((len(names)-1)/2-index)*1.6)
               for level,names in columns.items()for index,name in enumerate(names)}
    return positions,levels

def label(node,frozen):
    lines=[str(node['id'])[:42]];proof=node.get('verification')or{};score=node.get('development_score')
    if node.get('kind')=='review':lines.append('review suggestion (unverified)')
    elif score:
        count=len(score.get('feedback')or[]);value=str(score.get('solved','?'))
        lines.append('dev solved '+value+('/'+str(count)if count else'')+'; penalty '+str(score.get('penalty','?')))
    elif proof.get('solved')is True:lines.append('EXACT SOLUTION — recorded proof')
    elif proof.get('valid_schema')is False:lines.append('invalid assignment schema')
    elif proof.get('valid_schema')is True:lines.append(str(proof.get('conflicts','?'))+' conflicts; repairable')
    operation=node.get('operation')
    if operation:lines.append(str(operation).replace('_',' ')[:35])
    if node.get('origin')=='derived':lines.append('derived; no model call')
    if frozen:lines.append('FROZEN FOR EVALUATION')
    return '\n'.join(lines).replace('$',r'\$')

def render(document,output,title='Search lineage DAG'):
    positions,levels=layout(document)
    targets=[Path(str(output)+'.svg'),Path(str(output)+'.png')]
    if any(p.exists()for p in targets):raise FileExistsError('Refusing to overwrite an exported figure')
    # The pure layout/help paths never import plotting libraries.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyArrowPatch
    plt.rcParams['svg.fonttype']='none'
    depth=max(levels.values())+1;width=max(sum(v==level for v in levels.values())for level in set(levels.values()))
    size=(max(9,depth*2.5),max(5,width*1.5+2));fig,ax=plt.subplots(figsize=size)
    parallel=defaultdict(list)
    for edge in document['edges']:parallel[edge['source'],edge['target']].append(edge)
    relations={edge.get('relation','edge')for edge in document['edges']}
    boxes={}
    selected=document.get('selected_program')or{};selected_id='program-'+str(selected.get('candidate_index'))
    pruned={name for event in document.get('selections',[])for name in event.get('pruned_ids',[])}
    for node in document['nodes']:
        name=node['id'];frozen=node.get('selected')is True or name==selected_id
        exact=(node.get('verification')or{}).get('solved')is True
        face='#FFF2CC'if node.get('kind')=='review'else'#DFF3ED'if node.get('origin')=='derived'else'#F3F5F7'
        border='#6F42C1'if frozen else'#009E73'if exact else'#666666'
        text=ax.text(*positions[name],label(node,frozen),ha='center',va='center',fontsize=8,zorder=3,
            bbox=dict(boxstyle='round,pad=.4',facecolor=face,edgecolor=border,
                      linewidth=2.4 if frozen or exact else 1,linestyle='--'if name in pruned and not frozen else'-'))
        boxes[name]=text.get_bbox_patch()
    legends=[Line2D([0],[0],color=STYLES.get(r,('#666666',':'))[0],linestyle=STYLES.get(r,('#666666',':'))[1],label=r.replace('_',' '))for r in sorted(relations)]
    legends += [Line2D([0],[0],color='#009E73',linewidth=2.4,label='Exact solution: recorded verifier proof'),
                Line2D([0],[0],color='#6F42C1',linewidth=2.4,label='Explicitly frozen/selected source'),
                Line2D([0],[0],color='#666666',linestyle='--',label='Pruned from population; not a correctness judgment')]
    xs,ys=zip(*positions.values());ax.set(xlim=(min(xs)-2,max(xs)+2),ylim=(min(ys)-1.2,max(ys)+1.2),title=title);ax.axis('off')
    ax.legend(handles=legends,loc='upper left',bbox_to_anchor=(0,-.03),ncol=3,fontsize=8,frameon=False)
    fig.text(.01,.01,'DAG retains every recorded edge. Conflicts may be repaired; unselected does not mean incorrect. Layout is not evidence of causal contribution.',fontsize=8)
    fig.subplots_adjust(bottom=min(.3,1.4/size[1]),top=.94,left=.02,right=.98)
    # Initialize real text extents after layout; clip arrows to each box boundary.
    fig.canvas.draw()
    for(a,b),edges in parallel.items():
        for index,edge in enumerate(edges):
            relation=edge.get('relation','edge');color,style=STYLES.get(relation,('#666666',':'))
            curve=.14*(index-(len(edges)-1)/2)
            ax.add_patch(FancyArrowPatch(positions[a],positions[b],patchA=boxes[a],patchB=boxes[b],
                arrowstyle='-|>',mutation_scale=12,linewidth=1.3,color=color,linestyle=style,
                alpha=.8,shrinkA=3,shrinkB=3,connectionstyle=f'arc3,rad={curve}',zorder=1))
    targets[0].parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(targets[0],bbox_inches='tight');dpi=min(140,math.sqrt(30_000_000/(size[0]*size[1])))
    fig.savefig(targets[1],dpi=dpi,bbox_inches='tight');plt.close(fig)
    return targets

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lineage',type=Path,help='One explicit lineage JSON from report_completed_studies.py')
    parser.add_argument('--output',type=Path,required=True,help='New filename prefix; writes .svg and .png')
    parser.add_argument('--title',default='Search lineage DAG')
    args=parser.parse_args(argv);document=json.loads(args.lineage.read_text())
    for path in render(document,args.output,args.title):print(path)
if __name__=='__main__':main()
