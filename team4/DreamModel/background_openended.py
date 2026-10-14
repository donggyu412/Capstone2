"""Independent memory-conditioned reaction/diffusion and spatial evolution.

Three coupled activator/inhibitor systems compete for finite regional capacity.
An evolutionary search actually rolls candidate reaction/diffusion parameters
forward and selects by memory fitness, novelty and scale diversity. This is a
bounded artistic activator/inhibitor model, not a claim of unbounded OEE or an
exact Gray-Scott reproduction. It contains no GridModel or Team3 particle code.
"""
import math
import numpy as np
from .developmental_world import ease


class BackgroundOpenEnded:
    GENE_NAMES=('activator_diffusion','inhibitor_diffusion','self_activation',
                'inhibition','deposition','extinction')
    LOW=np.array([.30,.75,.23,.12,.065,.012])
    HIGH=np.array([1.15,2.2,.65,.43,.15,.065])

    def __init__(self,patches,seed,memory,*,evolution=True,competition=True,memory_bias=True,story_focus=None):
        self.rng=np.random.default_rng(seed);self.n=len(patches)
        self.distance=np.array([p.distance for p in patches]);self.centers=np.array([p.center for p in patches])
        self.flags={'evolution':evolution,'competition':competition,'memory_bias':memory_bias}
        lookup={p.index:i for i,p in enumerate(patches)};edges=[]
        for i,p in enumerate(patches):edges.extend((i,lookup[j]) for j in p.neighbors if j in lookup)
        self.rows=np.array([x for x,y in edges]);self.cols=np.array([y for x,y in edges])
        color=np.array([p.color for p in patches]);lum=color@np.array([.2126,.7152,.0722])
        contrast=np.linalg.norm(color[self.rows]-color[self.cols],axis=1)
        sums=np.bincount(self.rows,weights=np.exp(-contrast*2),minlength=self.n)
        self.base=np.exp(-contrast*2)/np.maximum(sums[self.rows],1e-6)
        local_edge=np.bincount(self.rows,weights=contrast,minlength=self.n)/np.maximum(np.bincount(self.rows,minlength=self.n),1)
        # Three source-derived memories: boundaries, mid-tone material, broad space.
        self.memory=np.array([.25+np.clip(local_edge*3,0,.75), .25+.7*(1-abs(lum-.45)),
                              .25+.4*lum+.30*(1-self.distance)])
        if not memory_bias:self.memory[:]=.5
        self.story_bias=(np.exp(-np.sum(((self.centers-np.asarray(story_focus))/[.27,.20])**2,axis=1))
                         if story_focus is not None else np.zeros(self.n))
        self.memory=np.clip(self.memory+.14*self.story_bias[None,:],0,1)
        self.trace=memory.copy()
        self.phase=np.array([self.centers@np.array([f,f*.7])+s*2.1+self.rng.normal(0,.10,self.n)
                             for s,f in enumerate((10.,5.,2.5))])
        self.u=.045*self.memory+.20*memory[None,:]
        self.u[:,self.distance<.075]+=.25
        self.v=np.zeros_like(self.u);self.mass=np.zeros_like(self.u)
        self.material=np.zeros(self.n);self.a=np.zeros(self.n);self.b=np.zeros(self.n)
        self.formed_extent=np.zeros(self.n)
        base=np.array([[.40,1.05,.38,.24,.12,.024],
                       [.62,1.40,.42,.25,.115,.025],
                       [.85,1.80,.45,.26,.11,.027]])
        self.genes=base.copy();self.selected=base.copy()
        self.population=[np.clip(base+self.rng.normal(0,.05,base.shape)*(self.HIGH-self.LOW),self.LOW,self.HIGH) for _ in range(6)]
        self.archive={};self.history=[];self.events=[];self.next_search=0.;self.updates=0
        self.extinction=np.zeros(3);self.rebirth=np.zeros(3);self.previous_dominant=np.zeros(self.n,dtype=int)
        self.dominance_changes=0;self.last_rates=np.zeros_like(self.mass)
        self.retreat=np.zeros(self.n);self.local_extinctions=np.zeros(3,dtype=int)
        self.starvation=np.zeros_like(self.mass);self.cooldown=np.zeros_like(self.mass)
        self.local_reseeds=np.zeros(3,dtype=int)

    def neighbor(self,x,hops=1):
        result=x
        for _ in range(hops):result=np.bincount(self.rows,weights=self.base*result[self.cols],minlength=self.n)
        return result

    def derivative(self,u,v,mass,genes,age,front,affect,energy,tension,coherence):
        du=np.zeros_like(u);dv=np.zeros_like(v);dm=np.zeros_like(mass)
        total=mass.sum(0)
        capacity=np.clip(1-total,0,1) if self.flags['competition'] else np.clip(1-mass,0,1)
        # Slowly changing source-conditioned niches prevent one scale from
        # monopolizing the whole space; these are conditions, not a colour tint.
        competition_age=float(ease((age-25)/12))
        niche=.5+.5*np.sin(age*.13+self.phase)
        for s,hops in enumerate((1,2,4)):
            da,db,activation,inhibition,growth,death=genes[s]
            neighbor_u=self.neighbor(u[s],hops);neighbor_v=self.neighbor(v[s],hops)
            memory=self.memory[s]
            drive=(.10+.08*memory+.025*self.trace)*front*(1-.85*u[s])*(.78+.22*niche[s])
            du[s]=da*(neighbor_u-u[s])+activation*u[s]*(1-u[s])-inhibition*v[s]*u[s]+drive
            dv[s]=db*(neighbor_v-v[s])+.17*u[s]-.24*v[s]
            resource=capacity if self.flags['competition'] else capacity[s]
            # Cyclic asymmetric inhibition creates local winners/losers without
            # granting the same scale a permanent advantage across the image.
            rivalry=((.035*(total-mass[s])*(1-competition_age)+competition_age*
                       (.40*mass[(s+1)%3]+.12*mass[(s-1)%3])) if self.flags['competition'] else 0.)
            pressure=death*(.45+.6*v[s]+.25*affect+.25*tension)*(.75+.25*niche[s])
            niche_growth=1-competition_age+competition_age*(.15+.85*niche[s])
            dm[s]=growth*front*(.50+.50*u[s])*(.62+.38*memory)*resource*(.90+.24*energy)*niche_growth
            dm[s]-=pressure*mass[s]+rivalry*mass[s]*(1-.3*coherence)
            dm[s]=np.where(self.cooldown[s]>0,np.minimum(dm[s],0),dm[s])
        return du,dv,dm

    def descriptor(self,mass):
        shares=mass.mean(1);shares=shares/max(shares.sum(),1e-9)
        total=mass.sum(0)
        gradient=float(np.mean(abs(total[self.rows]-total[self.cols])))
        return np.array([*shares,float(total.mean()),float(total.std()),gradient])

    def search(self,age,front,affect,energy,tension,coherence):
        pool=list(self.population);parents=list(self.archive.values())
        for _ in range(5):
            a,b=([parents[int(self.rng.integers(len(parents)))]['genes'] for _ in range(2)] if parents else
                 [pool[int(self.rng.integers(len(pool)))] for _ in range(2)])
            sigma=.03+.035*affect+.035*tension+.02*energy
            child=np.clip((a+b)/2+self.rng.normal(0,sigma,a.shape)*(self.HIGH-self.LOW),self.LOW,self.HIGH)
            pool.append(child)
        candidates=[]
        for genes in pool:
            u,v,m=self.u.copy(),self.v.copy(),self.mass.copy()
            for step in range(6):
                du,dv,dm=self.derivative(u,v,m,genes,age+step*.22,front,affect,energy,tension,coherence)
                u=np.clip(u+.22*du,0,1);v=np.clip(v+.22*dv,0,1);m=np.clip(m+.22*dm,0,1)
            feature=self.descriptor(m);total=m.sum(0)
            expected=front*(.32+.40*self.memory.mean(0))
            memory_fit=float(1-np.mean(abs(total-expected)))
            stability=float(1-np.clip(np.mean(abs(total[self.rows]-total[self.cols]))*3,0,1))
            entropy=float(-np.sum(feature[:3]*np.log(np.maximum(feature[:3],1e-9)))/math.log(3))
            novelty=float(np.mean(sorted(np.linalg.norm(feature-h) for h in self.history)[0:4])) if self.history else .1
            fitness=.68*memory_fit+.32*stability
            diversity=entropy
            key=(int(feature[0]*6),int(feature[1]*6),int(feature[4]*12),int(feature[5]*30))
            row={'genes':genes.copy(),'feature':feature,'fitness':fitness,'novelty':novelty,'diversity':diversity,'key':key}
            previous=self.archive.get(key)
            if previous is None or previous['fitness']<fitness:self.archive[key]=row
            candidates.append(row)
        # Retain several good candidates; novelty and scale balance influence
        # the actual chosen generator, not just a diagnostic number.
        for c in candidates:c['score']=.68*c['fitness']+.20*c['novelty']+.12*c['diversity']
        ranked=sorted(candidates,key=lambda c:c['score'],reverse=True)
        weights=np.array([math.exp((c['score']-ranked[0]['score'])*18) for c in ranked[:6]])
        weights/=weights.sum();winner=ranked[int(self.rng.choice(min(6,len(ranked)),p=weights))]
        self.selected=winner['genes'].copy();self.population=[c['genes'].copy() for c in ranked[:6]]
        self.history.append(winner['feature'].copy());self.history=self.history[-60:]
        self.events.append({'age':round(age,3),'chosen_genes':self.selected.tolist(),
            'fitness':winner['fitness'],'novelty':winner['novelty'],'diversity':winner['diversity'],
            'candidate_count':len(candidates),'archive_cells':len(self.archive),
            'candidates':[{'fitness':c['fitness'],'novelty':c['novelty'],'diversity':c['diversity'],
                           'score':c['score'],'genes':c['genes'].tolist()} for c in candidates]})

    def step(self,age,dt,affect,energy,coherence,tension,arousal=.5):
        front=ease((age-(.7+self.distance*(22+3*tension)-self.trace*4-self.story_bias*2.5))/5)
        if self.flags['evolution'] and age+1e-7>=self.next_search:
            self.search(age,front,affect,energy,tension,coherence);self.next_search+=8-2*arousal
        self.genes+=(self.selected-self.genes)*(1-math.exp(-dt/5))
        du,dv,dm=self.derivative(self.u,self.v,self.mass,self.genes,age,front,affect,energy,tension,coherence)
        old=self.mass.copy();self.u=np.clip(self.u+dt*du,0,1);self.v=np.clip(self.v+dt*dv,0,1)
        self.mass=np.clip(self.mass+dt*dm,0,1);self.last_rates=dm
        ended=(self.cooldown>0)&(self.cooldown<=dt)
        self.cooldown=np.maximum(0,self.cooldown-dt)
        if np.any(ended):
            self.mass[ended]=.012*self.memory[ended]
            self.u[ended]=.08*self.memory[ended]
            self.local_reseeds+=np.count_nonzero(ended,axis=1)
        shares=self.mass/np.maximum(self.mass.sum(0),1e-8)
        weak=(shares<.24)&(self.mass<.15)&(dm<-.0015)&(age>30)&self.flags['competition']
        self.starvation=np.where(weak,self.starvation+dt,np.maximum(0,self.starvation-dt))
        dies=(self.starvation>=4)&(self.cooldown==0)
        if np.any(dies):
            self.mass[dies]=0;self.u[dies]=.025*self.memory[dies]
            self.cooldown[dies]=8+4*affect;self.starvation[dies]=0
            self.local_extinctions+=np.count_nonzero(dies,axis=1)
        self.extinction+=np.count_nonzero((old>.04)&(self.mass<old-1e-6),axis=1)*dt
        self.rebirth+=np.count_nonzero((old>.04)&(self.mass>old+1e-6),axis=1)*dt
        # Negative local biomass flux contracts the material itself. Smooth the
        # response to retain a slow dream rhythm, rather than flickering patches.
        loss=np.clip(np.maximum(-dm,0).sum(0)*25,0,.5)
        self.retreat+=(loss-self.retreat)*(1-math.exp(-dt/3.5))
        self.material=np.clip(self.mass.sum(0)*1.55-self.retreat*.40,0,1)
        self.formed_extent=np.maximum(self.formed_extent,self.material)
        self.a=np.mean(self.u,axis=0);self.b=np.mean(self.v,axis=0)
        dominant=np.argmax(self.mass,axis=0)
        self.dominance_changes+=int(np.count_nonzero((dominant!=self.previous_dominant)&(self.mass.sum(0)>.15)))
        self.previous_dominant=dominant
        self.trace=np.clip(self.trace*math.exp(-dt/65)+dt*.012*self.material,0,1);self.updates+=1

    def report(self):
        shares=self.mass.mean(1);shares=shares/max(shares.sum(),1e-9)
        return {'method':'memory-conditioned activator/inhibitor RD + evolved parameters + 3-scale resource competition',
            'flags':self.flags,'gene_names':self.GENE_NAMES,'current_genes':self.genes.tolist(),
            'story_memory_bias_mean':float(self.story_bias.mean()),
            'scale_shares':shares.tolist(),'declining_region_seconds':self.extinction.tolist(),
            'regrowing_region_seconds':self.rebirth.tolist(),'dominance_changes':self.dominance_changes,
            'local_extinctions':self.local_extinctions.tolist(),'local_reseeds':self.local_reseeds.tolist(),
            'viability_rule':'share < .24, biomass < .15, declining > .0015/sec for 4 seconds; remove local scale, reseed from memory after 8+4*affect seconds',
            'search_events':self.events,'limit':'bounded irregular-graph artistic RD, not unbounded OEE or exact Gray-Scott'}
