"""Couple evolving topology to regional emergence without displaying a skeleton."""
from __future__ import annotations
from dataclasses import replace
from copy import copy
import cv2
import numpy as np
from .geometric_evolution import Evolution
from .memory_grammar import MemoryField
from .background_evolution import BackgroundEvolution


def align_memory(scene,composition,library,spatial_reference,width,height):
    memory=MemoryField(replace(scene,background_path=spatial_reference),library)
    layouts={x['object_id']:x for x in composition.layout}
    for motif in memory.motifs:
        if motif.family not in layouts:continue
        layout=layouts[motif.family]
        motif.center=np.asarray(layout['center_normalized'],dtype=float)
        yspan=max(np.ptp(motif.path,axis=0)[1],.01)
        sy=layout['height_fraction']/yspan
        motif.extent=np.array([sy*height/width*layout['horizontal_projection_scale'],sy])
        angle=np.deg2rad(layout['rotation_degrees'])
        c,s=np.cos(angle),np.sin(angle)
        motif.path=motif.path@np.array([[c,s],[-s,c]])
    return memory


class EvolvingBrush:
    def __init__(self,fields,seed,atmosphere=None):
        object_fields=[]
        for field in fields:
            object_field=copy(field)
            object_field.motifs=[m for m in field.motifs if m.family!='space']
            if not object_field.motifs:raise ValueError('Object-centered evolution requires supplied object memories')
            object_fields.append(object_field)
        self.engine=Evolution(object_fields,seed,atmosphere=atmosphere)
        self.background=BackgroundEvolution(fields,seed,atmosphere)
        self.engine.spatial_field=self.background.field
        self.engine.enter_scene(0)
        self.rng=np.random.default_rng(seed+7301)
        self.credits={}
        self.brush_marks=0
        self.topology_marks=0
        self.attention=np.zeros((54,96),dtype='float32')
        self.updates=0

    def enter_scene(self,index):
        self.engine.enter_scene(index)
        self.background.enter_scene(index)

    def step(self,phase,dt,rms,onset):
        # Ten developmental units occupy a real 75-second scene. Wall/audio/video
        # clocks remain seconds; selection is dt-based, independent of frame count.
        self.engine.step(phase,dt/7.5,rms,onset)
        self.updates+=1
        if self.updates%6==1:
            field=np.zeros_like(self.attention)
            for o in self.engine.population:
                if o.dying:continue
                points=(o.controlPoints*np.array([96,54])).astype('int32')
                value=float(o.energy*(.45+.55*o.fitness))
                for a,b in o.connections:
                    cv2.line(field,tuple(points[a]),tuple(points[b]),value,3,cv2.LINE_AA)
            field=cv2.GaussianBlur(field,(0,0),4)
            self.attention=field/max(float(field.max()),.1)
        self.background.step(dt,rms,self.attention)

    def paint(self,painter,memory,phase,dt,rms):
        for o in self.engine.population:
            # An organism's survival, branching and parent exchange determine
            # which connected marks can actually keep depositing pigment.
            credit=self.credits.get(o.uid,0.)+dt*(.55+.60*rms)*max(0,o.energy)
            self.credits[o.uid]=credit
            if credit<1 or o.dying or len(o.connections)<1:continue
            self.credits[o.uid]-=1
            a,b=o.connections[int(self.rng.integers(len(o.connections)))]
            edge=o.controlPoints[[a,b]]*np.array([painter.w,painter.h])
            span=float(np.linalg.norm(edge[1]-edge[0]))
            if span<3:continue
            # The graph defines where matter can develop, not a visible wire
            # frame. Sample a local growth region on a surviving branch and
            # diffuse it; never trace the full connection across the scene.
            radius=(20 if o.motif.family=='space' else 14)*painter.w/960
            length=min(span,radius*1.25)
            tangent=(edge[1]-edge[0])/span
            normal=np.array([-tangent[1],tangent[0]])
            middle=edge[0]+(edge[1]-edge[0])*self.rng.uniform(.15,.85)
            u=np.linspace(-.5,.5,7)
            points=middle+u[:,None]*length*tangent
            points+=np.sin((u+.5)*np.pi)[:,None]*radius*.25*normal
            x,y=np.clip(middle.astype(int),(0,0),(painter.w-1,painter.h-1))
            local=painter.canvas[y,x]
            pigment=o.colorTraits*.18+local*.82
            painter.stroke(memory,int(x),int(y),radius,length,.12,1,phase,
                path=points,pigment=pigment,duration=4.+self.rng.random()*3.)
            self.brush_marks+=1
            self.topology_marks+=int(o.mutations>0 or len(o.lineage)>1)

    def report(self):
        from collections import Counter
        events=[{**e,'original_seconds':round(e['time']*7.5,4)} for e in self.engine.events]
        return {'algorithm':'structural mutation + graph recombination + fitness/novelty/diversity selection',
                'event_counts':dict(Counter(e['type'] for e in events)),'events':events,
                'inheritance':self.engine.transfers,'organism_brush_marks':self.brush_marks,
                'mutated_or_recombined_brush_marks':self.topology_marks,
                'descriptor_archive_size':len(self.engine.archive),'state':self.engine.snapshot(),
                'background':self.background.report(),
                'scope':'Object graphs only; background uses independent region-program evolution.',
                'limit':'Finite grammar and bounded population; not proof of unlimited open-endedness.'}
