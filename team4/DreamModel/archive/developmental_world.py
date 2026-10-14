"""Typed developmental geometry, cooperative search and a quality-diversity archive.

The phenotype is visible geometry, not an attention mask over a target image.
The finite room/book/body grammar is an explicit artistic interpretation of the
supplied semantic roles, not learned 3D reconstruction or unrestricted OEE.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from copy import deepcopy
import math
import numpy as np
from team4.DreamModel.runtime.audience import AudienceAtmosphere
from team4.DreamModel.runtime.math_utils import ease




@dataclass
class Program:
    uid: int
    kind: str
    genes: np.ndarray
    nodes: tuple[str,...]
    lineage: tuple[int,...]
    quality: float = 0.

    def descriptor(self):
        # Feature-space archive bins describe morphology, not canvas pixels.
        if self.kind=='space':return (len(self.nodes),int(self.genes[0]*4),int(self.genes[1]*4))
        return (len(self.nodes),int(self.genes[2]*4),int(self.genes[3]*4))


class CooperativeArchive:
    """MAP-Elites-style per-type archives, evaluated with partner contexts.

    Novelty affects parent sampling; quality replacement happens inside each
    descriptor cell. A single weighted score without cells is not used as QD.
    """
    def __init__(self,seed,atmosphere,story=True,emotion=True,sound=True):
        self.rng=np.random.default_rng(seed);self.atmosphere=atmosphere
        self.enabled={'story':story,'emotion':emotion,'sound':sound}
        self.archives={k:{} for k in ('space','journal','figure','record','pool')}
        self.population={};self.next_id=0;self.events=[];self.generation=0
        self.semantic_targets={}
        for kind in self.archives:
            count=4 if kind=='space' else (3 if kind in ('journal','record') else 2)
            self.population[kind]=[self.create(kind,np.clip(.5+self.rng.normal(0,.12,6),.05,.95),count) for _ in range(6)]
        self.champions={k:v[0] for k,v in self.population.items()}

    def create(self,kind,genes,count,parents=()):
        self.next_id+=1
        prefix={'space':'bay','journal':'page','record':'sheet','figure':'arm_joint','pool':'ripple'}[kind]
        nodes=tuple(f'{prefix}_{i}' for i in range(count))
        lineage=tuple(dict.fromkeys((*parents,self.next_id)))
        return Program(self.next_id,kind,genes.copy(),nodes,lineage)

    def joint_quality(self,space,obj,scene,semantic_weight):
        # Partner-dependent geometric/semantic proxies; visual acceptance is
        # still a human check, not asserted from this score.
        corridor_width=2.1+space.genes[0]*1.2
        spread=.9+obj.genes[1]*.65
        room_fit=np.clip((corridor_width-spread)/1.3,0,1)
        form_fit=1-abs(obj.genes[2]-.5)*.55
        compatible=1-abs(space.genes[4]-obj.genes[4])*.65
        placement=1-abs(space.genes[3]-obj.genes[3])*.5
        target=self.semantic_targets.get(obj.kind,.5)
        salient=1.-abs(obj.genes[3]-target)
        return float(.27*room_fit+.27*form_fit+.20*compatible+.16*placement+.10*salient*semantic_weight)

    def evolve(self,seconds,scene,rms,onset,intensity):
        self.generation+=1;a=self.atmosphere
        energy=rms if self.enabled['sound'] else 0.
        impulse=onset if self.enabled['sound'] else 0.
        affect=intensity if self.enabled['emotion'] else 0.
        spread=.035+.035*affect+.025*a.tension+.015*energy
        semantic_weight=1. if self.enabled['story'] else .0
        for kind in self.population:
            archive=self.archives[kind]
            parents=list(archive.values()) or self.population[kind]
            candidates=list(self.population[kind])
            for _ in range(6):
                p,q=[parents[int(self.rng.integers(len(parents)))] for _ in range(2)]
                genes=np.clip((p.genes+q.genes)*.5+self.rng.normal(0,spread,6),.02,.98)
                count=len(p.nodes)
                structural=self.rng.random()<.50+.18*impulse+.12*a.arousal
                if structural:count=int(np.clip(count+self.rng.choice((-1,1)),2,7 if kind=='space' else 5))
                child=self.create(kind,genes,count,(*p.lineage,*q.lineage))
                candidates.append(child)
            for candidate in candidates:
                if kind=='space':
                    contexts=[self.champions['journal' if scene==0 else 'record'],self.champions['figure']]
                    candidate.quality=float(np.mean([self.joint_quality(candidate,o,scene,semantic_weight) for o in contexts]))
                else:
                    partners=self.population['space'][:2]
                    candidate.quality=float(np.mean([self.joint_quality(b,candidate,scene,semantic_weight) for b in partners]))
                key=candidate.descriptor()
                if candidate.quality>=.62 and (key not in archive or archive[key].quality<candidate.quality):
                    archive[key]=candidate
            valid=list(archive.values())
            if not valid:valid=sorted(candidates,key=lambda p:p.quality,reverse=True)[:6]
            previous=self.champions[kind]
            # Preserve quality, explore different structural archive cells.
            weights=np.array([p.quality*(1.+.6*(p.descriptor()!=previous.descriptor())) for p in valid])
            weights/=weights.sum()
            selected=valid[int(self.rng.choice(len(valid),p=weights))]
            self.champions[kind]=selected
            self.population[kind]=sorted(candidates,key=lambda p:p.quality,reverse=True)[:6]
            self.events.append({'seconds':round(seconds,3),'type':kind,'id':selected.uid,
                'parents':list(selected.lineage[:-1]),'nodes':len(selected.nodes),'quality':selected.quality,
                'descriptor':selected.descriptor(),'changed_topology':selected.nodes!=previous.nodes})

    def report(self):
        return {'method':'typed structural mutation/recombination, cooperative partner scoring, descriptor-cell quality-diversity archive',
            'generations':self.generation,'archive_cells':{k:len(v) for k,v in self.archives.items()},
            'events':self.events,'enabled':self.enabled,'fitness':'geometric and semantic proxies; no target-pixel error',
            'limit':'Finite artistic grammar; does not establish unbounded open-ended evolution.'}


class DevelopmentalWorld:
    def __init__(self,plans,seed=101,atmosphere=None,*,story=True,emotion=True,sound=True,memory=True,
                 memories=None,events=None):
        self.plans=plans;self.atmosphere=atmosphere or AudienceAtmosphere()
        self.search=CooperativeArchive(seed,self.atmosphere,story,emotion,sound)
        self.enabled=self.search.enabled;self.memory_enabled=memory
        self.events=events;self.channels={};self.development_time=0.;self.incoming_development=0.;self.onset_rate=0.
        self.asset_bias={k:np.zeros(6) for k in self.search.population}
        if memories is not None:
            for kind in self.asset_bias:
                values=[v for (sid,role),v in memories.shape_features.items() if role==kind and sid<=2]
                if values:
                    v=np.mean(values,axis=0)
                    self.asset_bias[kind]=np.clip(np.array([v[0]-1,v[1]-.3,v[2]*4-.3,v[3]-.15,0,0]),-.5,.5)*.25
            self.asset_bias['space'][:2]=memories.spatial_bias
            for kind,programs in self.search.population.items():
                for p in programs:p.genes=np.clip(p.genes+self.asset_bias[kind],.02,.98)
        self.seed=seed;self.time=0.;self.scene=0;self.next_selection=0.
        self.genes={k:p.genes.copy() for k,p in self.search.champions.items()}
        self.node_amount={k:float(len(p.nodes)) for k,p in self.search.champions.items()}
        self.velocity={k:np.zeros(6) for k in self.genes}
        self.audio=np.zeros(2);self.inheritance=None;self.samples=[]
        self.transition=0.
        self.births={o.role:4.+7*o.reveal_rank for o in plans[0].objects}
        self.births.update({k:self.births.get(k,14.) for k in ('journal','pool','figure')})
        self.page_memory=np.array([[.34,.752],[.455,.748],[.486,.876],[.34,.884]],float)
        self.page_points=self.page_memory.copy();self.page_velocity=np.zeros((4,2))
        self.memory_field=np.zeros((54,96),np.float32)
        self.my,self.mx=np.mgrid[:54,:96].astype('float32')

    def step(self,time,dt,rms,onset):
        self.time=time
        audio_target=np.array([rms,onset]) if self.enabled['sound'] else np.zeros(2)
        self.audio+=(audio_target-self.audio)*(1-np.exp(-dt/1.8))
        self.onset_rate+=(float(self.audio[1])-self.onset_rate)*(1-np.exp(-dt/4.))
        self.channels=self.events.channels(time,enabled=self.enabled['story']) if self.events else {}
        intensity=self.plans[self.scene].emotion_intensity if self.enabled['emotion'] else 0.
        self.development_time+=dt*(.80+.16*float(self.audio[0])+.12*intensity)
        if time>=65:
            self.incoming_development+=dt*(.60+.22*intensity+.32*float(self.audio[0]))
        if time>=65 and self.scene==0:
            self.scene=1
            old=self.page_points.copy()
            self.inheritance={'seconds':time,'surface_before':old.tolist(),'surface_after':self.page_points.tolist(),
                'lineages':{k:list(p.lineage) for k,p in self.search.champions.items()},'retained':self.memory_enabled}
            if not self.memory_enabled:
                self.page_points=np.zeros_like(self.page_points);self.genes={k:np.full(6,.5) for k in self.genes}
                self.memory_field[:]=0
                self.search=CooperativeArchive(self.seed+7919,self.atmosphere,**self.enabled)
                self.next_selection=time
        self.transition=float(ease((time-65)/20))
        if time+1e-7>=self.next_selection:
            self.search.semantic_targets={o.role:.25+.25*o.reveal_rank for o in self.plans[self.scene].objects}
            intensity=self.plans[self.scene].emotion_intensity
            self.search.evolve(time,self.scene,float(self.audio[0]),float(self.audio[1]),intensity)
            self.next_selection+=6.
        for kind in self.genes:
            # Continuous damped development: new genotypes do not replace a
            # visible phenotype in a single frame.
            target=self.search.champions[kind].genes
            omega=.55+.12*self.atmosphere.coherence
            self.velocity[kind]+=(omega*omega*(target-self.genes[kind])-2*omega*self.velocity[kind])*dt
            self.genes[kind]+=self.velocity[kind]*dt
            n=len(self.search.champions[kind].nodes)
            self.node_amount[kind]+=(n-self.node_amount[kind])*(1-np.exp(-dt/6.5))
        # One existing page survives and becomes the first wall record. Its
        # actual 3D control points, not just its opacity, are carried over.
        q=self.transition
        wall=np.array([[.215,.385],[.315,.404],[.307,.607],[.218,.598]])
        relocation=float(ease((time-73)/19))
        target=self.page_memory*(1-relocation)+wall*relocation
        if self.enabled['story'] and self.events and self.events.enabled('erase_before_water'):
            fall=float(ease((time-127)/10))
            water=np.array([[.48,.815],[.56,.81],[.59,.861],[.47,.867]])
            target=target*(1-fall)+water*fall
        self.page_velocity+=(1.2**2*(target-self.page_points)-2.4*self.page_velocity)*dt
        self.page_points+=self.page_velocity*dt
        if self.memory_enabled:
            self.memory_field*=math.exp(-dt/48)
            reach=self.channels.get('reach',0)
            locations=[self.page_points.mean(axis=0),np.array([.54-.18*reach,.56+.14*reach])]
            for x,y in locations:
                self.memory_field+=np.exp(-((self.mx-x*96)**2/35+(self.my-y*54)**2/18))*dt*.045
            np.minimum(self.memory_field,1.,out=self.memory_field)

    def maturity(self,kind):
        order=self.births
        if not self.enabled['story']:order={'journal':14.,'pool':14.,'figure':14.}
        birth=order[kind]
        return float(ease((self.development_time-birth)/(29 if kind=='figure' else 25)))

    def snapshot(self):
        return {'seconds':self.time,'scene':self.scene+1,'transition':self.transition,
            'maturity':{k:self.maturity(k) for k in self.births},'visible_node_amount':self.node_amount.copy(),
            'page_control_points':self.page_points.tolist(),
            'story_channels':self.channels.copy(),'audio':self.audio.tolist(),
            'development_time':self.development_time,
            'incoming_development':self.incoming_development,
            'memory_field_mass':float(self.memory_field.sum()),
            'genes':{k:g.tolist() for k,g in self.genes.items()}}
