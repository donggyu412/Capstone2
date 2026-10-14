"""Two distinct bounded developmental systems on the original 300-second clock.

Space: continuous diffusion/reaction/deposition on an irregular region graph.
Objects: variable-length connected control graphs, recombination and QD selection.
Neither engine claims unlimited OEE or psychological validity of its parameters.
"""
from dataclasses import dataclass
import math
import numpy as np
from .developmental_world import ease
from .background_openended import BackgroundOpenEnded


@dataclass
class Organism:
    uid: int
    control: np.ndarray
    links: tuple
    parents: tuple
    quality: float = 0.
    novelty: float = 0.
    memory_fitness: float = 0.

    def descriptor(self):
        return (len(self.control), int(np.clip(self.control[:,2].mean()+.5,0,.999)*4),
                int(np.clip(self.control[:,3].std()*5,0,.999)*4))

    def features(self):
        return np.array([len(self.control)/8, *self.control[:,2:].mean(0),
                         *self.control[:,2:].std(0), np.mean([abs(a-b) for a,b in self.links])/8])


class ObjectEvolution:
    """Explicit fitness/novelty/archive diversity; morphology is a connected graph."""
    def __init__(self, seed, kinds, flags):
        self.rng=np.random.default_rng(seed); self.flags=flags; self.serial=0;self.events=[]
        self.archive={k:{} for k in kinds};self.champions={};self.population={}
        self.memory_targets={}
        for kind in kinds:
            initial=[self.make(self.initial(3+i%3)) for i in range(6)]
            self.population[kind]=initial;self.champions[kind]=initial[0]

    def initial(self,n):
        # x/y are attachment sites in object-local coordinates, z/w are bends.
        return np.column_stack((self.rng.uniform(.12,.88,(n,2)),self.rng.normal(0,.12,(n,2))))

    def make(self,control,parents=()):
        self.serial+=1
        # A rooted connected tree: each new control node attaches to an older one.
        links=tuple((i,int(self.rng.integers(i))) for i in range(1,len(control)))
        return Organism(self.serial,control,links,tuple(parents))

    def evolve(self,t,conditions,targets):
        affect,energy,arousal,tension,coherence=conditions
        for kind,pop in self.population.items():
            pool=list(self.archive[kind].values()) or pop
            children=[]
            for _ in range(8):
                a,b=[pool[int(self.rng.integers(len(pool)))] for _ in range(2)]
                delta=self.rng.choice((-1,0,1),p=(.18+.15*arousal,.64-.30*arousal,.18+.15*arousal))
                n=int(np.clip(len(a.control)+delta,2,7))
                ia=self.rng.integers(len(a.control),size=n);ib=self.rng.integers(len(b.control),size=n)
                c=.65*a.control[ia]+.35*b.control[ib]
                c+=self.rng.normal(0,.025+.025*affect+.035*tension+.02*energy,c.shape)
                c[:,:2]=np.clip(c[:,:2],.06,.94);c[:,2:]=np.clip(c[:,2:],-.42,.42)
                children.append(self.make(c,(a.uid,b.uid)))
            candidates=pop+children;features=np.array([p.features() for p in pool])
            for p in candidates:
                # A bounded memory/stability/relational proxy, not image recognition.
                bending=float(np.mean(p.control[:,2:]**2))
                spread=np.ptp(p.control[:,:2],axis=0).mean()
                target=targets.get(kind,.5)
                anchors=self.memory_targets.get(kind)
                if anchors is not None and self.flags['memory_bias']:
                    distances=np.linalg.norm(p.control[:,None,:2]-anchors[None,:,:],axis=2)
                    p.memory_fitness=float(np.clip(1-.7*distances.min(0).mean()-.5*distances.min(1).mean(),0,1))
                else:p.memory_fitness=.5
                stability=.65*(1-min(1,bending*3))+.35*min(1,spread/.6)
                p.quality=float(.40*p.memory_fitness+.40*stability+.20*(1-abs(len(p.control)/8-target)))
                distances=np.linalg.norm(features-p.features(),axis=1)
                p.novelty=float(np.mean(np.sort(distances)[:min(4,len(distances))]))
                cell=p.descriptor() if self.flags['diversity'] else (0,0,0)
                old=self.archive[kind].get(cell)
                if (not self.flags['selection'] or p.quality>.60) and (old is None or p.quality>old.quality):
                    self.archive[kind][cell]=p
            available=list(self.archive[kind].values()) or candidates
            weights=np.array([(p.quality**3 if self.flags['selection'] else 1.)*
                (1+2*p.novelty if self.flags['novelty'] else 1.) for p in available])
            weights/=weights.sum();chosen=available[int(self.rng.choice(len(available),p=weights))]
            old=self.champions[kind];self.champions[kind]=chosen
            self.population[kind]=sorted(candidates,key=lambda p:p.quality,reverse=True)[:6] if self.flags['selection'] else children[:6]
            self.events.append({'t':round(t,3),'role':kind,'id':chosen.uid,'parents':chosen.parents,
                'nodes':len(chosen.control),'links':chosen.links,'fitness':chosen.quality,
                'memory_fitness':chosen.memory_fitness,
                'novelty':chosen.novelty,'archive_cells':len(self.archive[kind]),
                'extinct_population_ids':[p.uid for p in candidates if p.uid not in {q.uid for q in self.population[kind]} and p is not chosen],
                'changed':chosen.uid!=old.uid})

    def inherit(self,source,target,t):
        if source==target:return
        a,b=self.champions[source],self.champions[target]
        n=max(2,round((len(a.control)+len(b.control))/2))
        ia=np.linspace(0,len(a.control)-1,n).round().astype(int)
        ib=np.linspace(0,len(b.control)-1,n).round().astype(int)
        child=self.make(.35*a.control[ia]+.65*b.control[ib],(a.uid,b.uid))
        self.champions[target]=child;self.population[target]=[child,*self.population[target][:5]]
        self.events.append({'t':round(t,3),'role':target,'id':child.uid,'parents':child.parents,
            'nodes':n,'links':child.links,'fitness':None,'memory_fitness':None,'novelty':None,
            'archive_cells':len(self.archive[target]),'extinct_population_ids':[],
            'changed':True,'cross_role_inheritance':{'source':source,'target':target,'source_weight':.35},
            'note':'new inherited candidate; evaluated at the next selection epoch'})


class SpatialGrowth:
    """Continuous activator, inhibitor, deposition and adaptive graph conductance.

    The source is irregular semantic image regions, not a pixel lattice/CA or
    Team3's image-colour particles. Diffusion biases an authored slow growth front.
    """
    def __init__(self,patches,seed,memory):
        self.rng=np.random.default_rng(seed);self.n=len(patches)
        self.distance=np.array([p.distance for p in patches]);self.centers=np.array([p.center for p in patches])
        lookup={p.index:i for i,p in enumerate(patches)};edges=[]
        for i,p in enumerate(patches):
            edges.extend((i,lookup[j]) for j in p.neighbors if j in lookup)
        self.rows=np.array([x for x,y in edges]);self.cols=np.array([y for x,y in edges])
        self.base=np.exp(-np.array([np.linalg.norm(patches[x].color-patches[y].color) for x,y in edges])*1.8)
        self.a=np.zeros(self.n);self.b=np.zeros(self.n);self.material=np.zeros(self.n)
        self.trace=memory.copy();self.phase=self.rng.uniform(0,math.tau,self.n)
        self.a[self.distance<.075]=.7;self.a+=.28*memory
        self.graph=None;self.next_graph=0.;self.updates=0

    def step(self,age,dt,affect,energy,coherence,tension):
        if age>=self.next_graph:
            w=self.base*(.65+.35*(self.material[self.rows]+self.material[self.cols])/2)
            sums=np.bincount(self.rows,weights=w,minlength=self.n)
            self.graph=w/np.maximum(sums[self.rows],1e-6)
            self.next_graph=age+1;self.updates+=1
        diffusion=np.bincount(self.rows,weights=self.graph*self.a[self.cols],minlength=self.n)-self.a
        inhibition=np.bincount(self.rows,weights=self.graph*self.b[self.cols],minlength=self.n)-self.b
        front=ease((age-(.7+self.distance*(22+3*tension)-self.trace*4))/5)
        drive=.13*front*(1-.8*self.a)*(1+.22*np.sin(age*.13+self.phase))
        da=.75*diffusion+.38*self.a*(1-self.a)-.14*self.b*self.a+drive+.025*self.trace
        db=1.2*inhibition+.16*self.a-.22*self.b
        self.a=np.clip(self.a+dt*da,0,1);self.b=np.clip(self.b+dt*db,0,1)
        rate=(.069+.027*energy+.012*affect)*(.70+.60*self.a+.22*coherence)
        renewal=float(ease((age-36)/12))
        resting=.92+.05*np.sin(age*.13+self.phase*.4)+(coherence-.5)*.02
        self.material=np.clip(self.material+dt*(rate*front*(1-renewal)+renewal*(resting-self.material)/6),0,1)
        self.trace=np.clip(self.trace*math.exp(-dt/65)+dt*.012*self.material,0,1)


class DreamWorld:
    def __init__(self,scenes,plans,templates,seed,audience,**overrides):
        self.scenes=scenes;self.plans=plans;self.templates=templates;self.seed=seed;self.audience=audience
        self.flags={k:True for k in ('story','emotion','sound','collective','memory','memory_bias','selection','novelty','diversity','background_evolution','pattern_competition')}
        self.flags.update(overrides)
        kinds=sorted({g.kind for s in templates for g in s.groups if g.kind!='space'})
        self.evolution=ObjectEvolution(seed,kinds,self.flags)
        self.memory_anchors=[]
        for template in templates:
            row={}
            for g in template.groups[1:]:
                low=g.quad.min(0);span=np.maximum(g.quad.max(0)-low,.01)
                # Real source contour region centres act as memory landmarks.
                regions=sorted(g.patches,key=lambda p:p.distance)
                selected=regions[::max(1,len(regions)//10)][:10]
                row[g.kind]=np.clip((np.array([p.center for p in selected])-low)/span,0,1)
            self.memory_anchors.append(row)
        self.audio=np.zeros(2);self.time=0.;self.next_selection=0.;self.states={};self.inheritance=[]
        self.controls={k:self.control_field(p) for k,p in self.evolution.champions.items()}
        self.node_counts={k:float(len(p.control)) for k,p in self.evolution.champions.items()}
        self.trace=np.zeros((54,96),np.float32);self.cy,self.cx=np.mgrid[:54,:96]
        self.samples=[]

    def control_field(self,p):
        # Rasterize the *control graph* onto a small continuous deformation field.
        yy,xx=np.mgrid[:9,:9]/8;field=np.zeros((9,9,2));weight=np.zeros((9,9))
        for a,b in p.links:
            for u in (0.,.5,1.):
                c=p.control[a]*(1-u)+p.control[b]*u
                w=np.exp(-((xx-c[0])**2+(yy-c[1])**2)/.12)
                field+=w[:,:,None]*c[2:];weight+=w
        return field/np.maximum(weight[:,:,None],.001)

    def begin(self,sid):
        if sid and not self.flags['memory']:
            self.evolution=ObjectEvolution(self.seed+sid*7919,list(self.evolution.population),self.flags)
            self.controls={k:self.control_field(p) for k,p in self.evolution.champions.items()}
            self.node_counts={k:float(len(p.control)) for k,p in self.evolution.champions.items()}
        template=self.templates[sid];memory=np.zeros(len(template.groups[0].patches))
        inherited=[]
        for i,p in enumerate(template.groups[0].patches):
            x,y=np.clip(p.center*[95,53],[0,0],[95,53]).astype(int)
            memory[i]=self.trace[y,x] if self.flags['memory'] else 0
        focal=min(self.plans[sid].objects,key=lambda o:o.reveal_rank).role
        focus=next((g.quad.mean(0) for g in template.groups[1:] if g.kind==focal),None) if self.flags['story'] else None
        spatial=BackgroundOpenEnded(template.groups[0].patches,self.seed+sid*331,memory,
            evolution=self.flags['background_evolution'],competition=self.flags['pattern_competition'],
            memory_bias=self.flags['memory_bias'],story_focus=focus)
        state={'start':max(0,sid*75-10),'space':spatial,'age':0.,'objects':{},'roots':{},'source_colors':{}}
        for group in template.groups[1:]:
            state['objects'][group.kind]=np.zeros(len(group.patches))
            roots=np.array([p.root for p in group.patches]);colors=np.array([p.color for p in group.patches])
            if sid and self.flags['memory']:
                previous=self.templates[sid-1]
                candidates=[g for g in previous.groups[1:] if g.family==group.family]
                if candidates:
                    old=candidates[0];oldstate=self.states[sid-1]['objects'][old.kind]
                    self.evolution.inherit(old.kind,group.kind,self.time)
                    living=[p for p,v in zip(old.patches,oldstate) if v>.35] or old.patches
                    for j,p in enumerate(group.patches):
                        donor=min(living,key=lambda q:np.linalg.norm(q.center-p.center))
                        roots[j]=p.root+np.clip(donor.center-p.root,-.14,.14)*.75
                        colors[j]=.82*p.color+.18*donor.color
                    inherited.append({'from':old.kind,'to':group.kind,'patches':len(group.patches)})
            state['roots'][group.kind]=roots;state['source_colors'][group.kind]=colors
        self.states[sid]=state
        if sid:self.inheritance.append({'t':self.time,'from_scene':sid,'to_scene':sid+1,
            'enabled':self.flags['memory'],'initial_trace_mass':float(memory.sum()),'structural_donors':inherited,
            'surviving_genomes':{k:p.uid for k,p in self.evolution.champions.items()} if self.flags['memory'] else {}})

    def step(self,t,dt,rms,onset):
        self.time=t
        self.audio+=(np.array([rms,onset])*(1 if self.flags['sound'] else 0)-self.audio)*(1-math.exp(-dt/1.8))
        sid=min(3,int(t//75));plan=self.plans[sid]
        intensity=plan.emotion_intensity if self.flags['emotion'] else 0.
        # The supplied label's declared artistic profile contributes stability;
        # it is never reclassified or mapped directly to a colour.
        profile=plan.emotion_parameters
        affect=intensity*(.65+.35*profile['noise_gain']/1.15)
        a=self.audience
        arousal,tension,coherence=(a.arousal,a.tension,a.coherence) if self.flags['collective'] else (0.,0.,0.)
        if t+1e-7>=self.next_selection:
            self.evolution.memory_targets.update(self.memory_anchors[sid])
            targets={o.role:.32+.09*o.reveal_rank for o in plan.objects} if self.flags['story'] else {}
            self.evolution.evolve(t,(affect,*self.audio[:1],arousal,tension,coherence),targets)
            self.next_selection+=7.
        for kind,p in self.evolution.champions.items():
            target=self.control_field(p)
            self.controls[kind]+=(target-self.controls[kind])*(1-math.exp(-dt/(4.8+2*coherence)))
            self.node_counts[kind]+=(len(p.control)-self.node_counts[kind])*(1-math.exp(-dt/6))
        for i in range(4):
            start=max(0,i*75-10)
            if t>=start and i not in self.states:self.begin(i)
        self.trace*=math.exp(-dt/52)
        for i,s in self.states.items():
            if t>(i+1)*75+20:continue
            age=t-s['start'];s['age']=age
            s['space'].step(age,dt,affect,float(self.audio[0]),coherence,tension,arousal)
            s['clock']=age*(.82+.14*affect)+self.audio[0]*.7
            groups=self.templates[i].groups
            ranks={o.role:o.reveal_rank for o in self.plans[i].objects}
            for g in groups[1:]:
                distance=np.array([p.distance for p in g.patches])
                order=ranks.get(g.kind,1) if self.flags['story'] else 1
                field=self.controls[g.kind];m=field.mean((0,1))
                birth=2.5+order*3+distance*(10+2*m[0])
                birth=np.maximum(birth,.7+g.support*24-3)
                front=ease((s['clock']-birth)/8)
                # The connected control graph influences birth branches and repair.
                phase=np.array([p.center[0]*11+p.center[1]*7 for p in g.patches])
                local_variation=.07*np.sin(phase+self.node_counts[g.kind])*(.3+affect+.6*tension)
                renewal=ease((age-34)/14)*(.5+.5*np.sin(age*.21+phase))
                target=np.clip(front*(1-(.11+.1*affect+.06*self.audio[0])*renewal+local_variation),0,1)
                values=s['objects'][g.kind]
                values+=(target-values)*(1-math.exp(-dt/(2.2+1.2*coherence)))
                positions=np.array([p.center for p in g.patches])
                if hasattr(self,'score'):positions=self.score.warp(positions,g.kind,i,self)
                xy=np.clip(positions*[95,53],[1,1],[94,52]).astype(int)
                deposit=dt*.013*values*(values>=.2)
                for dx,dy in ((-1,-1),(0,-1),(1,-1),(-1,0),(0,0),(1,0),(-1,1),(0,1),(1,1)):
                    index=(xy[:,1]+dy)*96+xy[:,0]+dx
                    self.trace+=np.bincount(index,weights=deposit,minlength=54*96).reshape(54,96)
        np.clip(self.trace,0,1,out=self.trace)

    def active(self):
        return [(i,s) for i,s in self.states.items() if self.time<(i+1)*75+20]

    def snapshot(self):
        return {'seconds':round(self.time,3),'scene':min(4,int(self.time//75)+1),
            'audio':self.audio.tolist(),'trace_mass':float(self.trace.sum()),
            'nodes':dict(self.node_counts),'active':{str(i+1):{'age':s['age'],
                'space_material':float(s['space'].material.mean()),'diffusion':float(s['space'].a.mean()),
                'objects':{k:float(v.mean()) for k,v in s['objects'].items()}} for i,s in self.active()}}
