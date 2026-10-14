"""Background region-program evolution, distinct from object graph evolution.

Spatial programs mutate/recombine under coherence, novelty and coverage
selection. Their slow continuous field directs deposition on the shared canvas;
this is neither object topology replay nor a cellular automaton.
"""
from __future__ import annotations
import numpy as np
from team4.DreamModel.runtime.audience import AudienceAtmosphere


class BackgroundEvolution:
    def __init__(self,memories,seed,atmosphere=None):
        self.memories=memories;self.scene_index=0
        self.atmosphere=atmosphere or AudienceAtmosphere()
        self.rng=np.random.default_rng(seed+8491)
        self.field=np.zeros((54,96),dtype='float32')
        self.yy,self.xx=np.mgrid[:54,:96]/np.array([54,96])[:,None,None]
        # center x/y, radius, elongation, orientation
        self.programs=np.column_stack((self.rng.uniform(.12,.88,(8,2)),
            self.rng.uniform(.12,.25,8),self.rng.uniform(1.,2.,8),self.rng.uniform(0,np.pi,8)))
        self.archive=[];self.elapsed=0.;self.time=0.;self.events=[];self.transfers=[]
        self.target=self.evaluate_field(self.programs)

    def evaluate_field(self,programs):
        field=np.zeros_like(self.field)
        for x,y,radius,elongation,angle in programs:
            dx=self.xx-x;dy=self.yy-y;c,s=np.cos(angle),np.sin(angle)
            u=(dx*c+dy*s)/(radius*elongation);v=(-dx*s+dy*c)/radius
            field+=np.exp(-2*(u*u+v*v)).astype('float32')
        return field/max(float(field.max()),.01)

    def enter_scene(self,index):
        before=self.field.copy();self.scene_index=index
        self.transfers.append({'into_scene':index+1,'retained_programs':len(self.programs),
            'field_preserved':bool(np.array_equal(before,self.field))})
        # Programs, their archive and current field persist. New background
        # statistics affect the next selection rather than replacing the field.

    def select(self):
        a=self.atmosphere;memory=self.memories[self.scene_index]
        candidates=[p.copy() for p in self.programs]
        spread=.025+.045*(1-a.coherence)+.02*a.tension
        for _ in range(8):
            parents=self.rng.choice(len(self.programs),2,replace=False)
            child=self.programs[parents].mean(axis=0)
            child+=self.rng.normal(0,(spread,spread,.025,.12,.13+.12*a.tension))
            child[:2]=np.clip(child[:2],.04,.96);child[2]=np.clip(child[2],.09,.29)
            child[3]=np.clip(child[3],1.,2.4);child[4]%=np.pi
            candidates.append(child)
        scored=[]
        for i,p in enumerate(candidates):
            fitness=memory.support(p[:2],np.array([np.cos(p[4]),np.sin(p[4])]))
            descriptor=p/np.array([1,1,.3,2.4,np.pi])
            novelty=min(1.,min((np.linalg.norm(descriptor-q) for q in self.archive[-48:]),default=1.))
            score=(.42+.18*a.coherence)*fitness+.25*novelty
            scored.append((score,i,descriptor))
        chosen=[];remaining=scored.copy()
        while len(chosen)<8:
            def merit(item):
                p=candidates[item[1]]
                coverage=min((np.linalg.norm(p[:2]-candidates[j][:2]) for j in chosen),default=.5)
                return item[0]+.22*min(1,coverage/.25)
            best=max(remaining,key=merit);remaining.remove(best);chosen.append(best[1])
            self.archive.append(best[2])
        self.programs=np.array([candidates[i] for i in chosen])
        self.target=self.evaluate_field(self.programs)
        self.events.append({'seconds':round(self.time,3),'scene':self.scene_index+1,
            'selected_mutated_programs':sum(i>=8 for i in chosen)})

    def step(self,dt,rms,object_attention):
        self.time+=dt;self.elapsed+=dt
        if self.elapsed>=6:
            self.elapsed-=6;self.select()
        # Objects leave a weak spatial influence on the surrounding atmosphere.
        target=np.clip(self.target*.88+object_attention*.12,0,1)
        tau=5.5+3.*self.atmosphere.coherence
        response=1-np.exp(-dt*(.9+.15*rms+.1*self.atmosphere.arousal)/tau)
        self.field+=(target-self.field)*response

    def report(self):
        return {'algorithm':'region-program mutation/recombination with spatial fitness, novelty archive and coverage selection',
            'generations':len(self.events),'events':self.events,'transfers':self.transfers,
            'population':8,'archive_size':len(self.archive),'continuous_field_response_seconds':[5.5,8.5],
            'limit':'Bounded regional search, not proof of unlimited open-endedness.'}
