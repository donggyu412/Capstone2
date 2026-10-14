"""Persistent pigment canvas: curved, textured brush marks, never a PNG reveal.

Reference imagery conditions pigment and local orientation. All visible color
has to be deposited by strokes. Previous pigment and stroke direction survive
the scene change and alter the next strokes.
"""
from __future__ import annotations
import cv2
import numpy as np


def smoothstep(x):
    x = np.clip(x,0,1)
    return x*x*(3-2*x)


class BrushMemory:
    def __init__(self, composition, seed,soft=False):
        rgb = composition.rgb
        self.h,self.w = rgb.shape[:2]
        self.labels = composition.labels
        # One global painterly exposure treatment, never an emotion colour map.
        rgb = np.power(np.clip(rgb,0,1),.80)
        rgb = cv2.bilateralFilter(rgb.astype('float32'),7,.12,7)
        luminance = rgb @ np.array([.2126,.7152,.0722],dtype='float32')
        rgb *= 1 + (1-luminance[:,:,None]) * np.array([-.025,.006,.035],dtype='float32')
        self.pigments = [cv2.GaussianBlur(rgb,(0,0),s) for s in ((15.,8.,3.5) if soft else (7.,3.,1.0))]
        # Fine memory is sampled into the same persistent material. It is never
        # pasted as a finished sprite or alpha-revealed over the background.
        self.pigments.append(cv2.GaussianBlur(rgb,(0,0),max(.5,self.w/960)))
        identity=(self.labels>0).astype('float32')
        self.identity=cv2.GaussianBlur(identity,(0,0),max(1.,self.w/960*2.))
        self.identity_small=cv2.resize(self.identity,(96,54),interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(luminance,(0,0),2)
        dx,dy = cv2.Sobel(gray,cv2.CV_32F,1,0),cv2.Sobel(gray,cv2.CV_32F,0,1)
        jxx=cv2.GaussianBlur(dx*dx,(0,0),5)
        jyy=cv2.GaussianBlur(dy*dy,(0,0),5)
        jxy=cv2.GaussianBlur(dx*dy,(0,0),5)
        self.angle = .5*np.arctan2(2*jxy,jxx-jyy)+np.pi/2
        self.importance = cv2.resize(.25+np.sqrt(dx*dx+dy*dy)*2+luminance*.5,(96,54))
        self.small_ref = cv2.resize(rgb,(96,54),interpolation=cv2.INTER_AREA)
        yy,xx=np.mgrid[:54,:96].astype('float32')
        x,y=xx/96,yy/54
        distance=np.minimum.reduce([np.hypot((x-.64)*.75,y-.56),
                                    np.hypot(x-.28,(y-.78)*.8)+.12,
                                    np.hypot(x-.43,y-.25)+.2])
        rng=np.random.default_rng(seed)
        stains=cv2.resize(rng.random((7,11)).astype('float32'),(96,54),interpolation=cv2.INTER_CUBIC)
        self.availability=distance*.42+stains*.09
        labels=cv2.resize(self.labels,(96,54),interpolation=cv2.INTER_NEAREST)
        for index,plan in enumerate(composition.plan.objects):
            self.availability[labels==index+1]=.23+.085*plan.reveal_rank
        self.intensity = composition.plan.emotion_intensity
        self.plan = composition.plan


class BrushPainter:
    def __init__(self,width,height,seed=101,soft=False):
        self.w,self.h=width,height
        self.soft=soft
        self.rng=np.random.default_rng(seed)
        self.canvas=np.empty((height,width,3),dtype='float32')
        self.canvas[:]=(.026,.031,.040)
        self.direction=np.zeros((height,width,2),dtype='float32')
        self.deposit=np.zeros((height,width),dtype='float32')
        self.credit=0.
        self.detail_credit=0.
        self.identity_strokes=0
        self.total_strokes=0
        self.xx,self.yy=np.meshgrid(np.arange(width,dtype='float32'),np.arange(height,dtype='float32'))
        grain=self.rng.random((height,width)).astype('float32')
        self.paper=cv2.GaussianBlur(grain,(0,0),.5)
        self.inherited_stroke_count=0
        self.wet_strokes=[]

    def inherit(self):
        # Preserve the very same canvas and directional memory, no new image layer.
        self.inherited_stroke_count=self.total_strokes
        self.credit=0.

    def stroke(self, memory, x, y, radius, length, opacity, level, phase,
               *, path=None,pigment=None,duration=0.,identity=False):
        rng=self.rng
        angle=float(memory.angle[y,x])
        prior=self.direction[y,x]
        if self.inherited_stroke_count and np.linalg.norm(prior)>.02:
            old=.5*np.arctan2(prior[1],prior[0])
            # Undirected orientation, so 180-degree wraps cannot flip the brush.
            delta=.5*np.arctan2(np.sin(2*(old-angle)),np.cos(2*(old-angle)))
            angle+=delta*.38*(1-phase)
        angle+=rng.normal(0,.07+.16*memory.intensity)
        tangent=np.array([np.cos(angle),np.sin(angle)])
        normal=np.array([-tangent[1],tangent[0]])
        t=np.linspace(-.5,.5,7)
        bend=rng.normal(0,.055+.035*memory.intensity)*length
        points=np.array([x,y])+t[:,None]*length*tangent+np.sin((t+.5)*np.pi)[:,None]*bend*normal
        if path is not None:
            points=np.asarray(path,dtype=float)
            direction=points[-1]-points[0]
            length=max(float(np.linalg.norm(direction)),1.)
            tangent=direction/length;normal=np.array([-tangent[1],tangent[0]])
            angle=float(np.arctan2(tangent[1],tangent[0]))
        left=max(0,int(points[:,0].min()-radius*1.5-3))
        right=min(self.w,int(points[:,0].max()+radius*1.5+4))
        top=max(0,int(points[:,1].min()-radius*1.5-3))
        bottom=min(self.h,int(points[:,1].max()+radius*1.5+4))
        if right<=left or bottom<=top:return
        shape=(bottom-top,right-left)
        mask=np.zeros(shape,dtype='uint8')
        local=(points-(left,top)).astype('int32')
        for i in range(len(local)-1):
            pressure=.55+.45*np.sin(np.pi*(i+.5)/(len(local)-1))
            cv2.line(mask,tuple(local[i]),tuple(local[i+1]),255,max(1,int(radius*pressure)),cv2.LINE_AA)
        ink=cv2.GaussianBlur(mask.astype('float32')/255,(0,0),max(.6,radius*(.48 if self.soft else .10)))
        gy,gx=np.mgrid[top:bottom,left:right].astype('float32')
        cross=(gx-x)*normal[0]+(gy-y)*normal[1]
        bristle=.76+.24*np.sin(cross*2.1+rng.uniform(0,6.28))**2
        dry=np.clip((self.paper[top:bottom,left:right]-.15)*1.7,.2,1)
        ink*=opacity if self.soft else bristle*(.74+.26*dry)*opacity
        if self.soft and not identity:
            # Broad atmospheric marks must not repeatedly wipe out already
            # growing object structure; feather the shared boundary.
            ink*=1-memory.identity[top:bottom,left:right]*.85*smoothstep((phase-.20)/.28)
        samples=np.clip(points.astype(int),(0,0),(self.w-1,self.h-1))
        # One pigment mixture per stroke; no target pixels are copied to the canvas.
        color=memory.pigments[level][samples[:,1],samples[:,0]].mean(axis=0)
        if pigment is not None:color=np.asarray(pigment,dtype='float32')
        color*=rng.uniform(.94,1.06)
        region=self.canvas[top:bottom,left:right]
        if self.inherited_stroke_count:
            color=color*.93+region.mean(axis=(0,1))*.07
        d=np.array([np.cos(2*angle),np.sin(2*angle)],dtype='float32')
        if duration>0:
            projection=((gx-points[0,0])*tangent[0]+(gy-points[0,1])*tangent[1])/length
            projection=np.clip(projection,-.1,1.1)
            self.wet_strokes.append({'bounds':(left,top,right,bottom),'ink':ink,'color':color,
                'direction':d,'projection':projection,'age':0.,'duration':duration,
                'origin':points[0].copy(),'tangent':tangent,'normal':normal,'length':length,
                'spread':radius*1.8+abs(bend),'identity':identity})
        else:
            self.apply_ink((left,top,right,bottom),ink,color,d)
        self.total_strokes+=1

    def develop_identity(self,memory,phase,dt,rms,attention):
        """Accumulate local folds, limbs and boundaries with multi-second growth."""
        # Keep the same narrative availability ordering. A late object does not
        # arrive fully formed just because a new scene becomes active.
        available=smoothstep((phase-memory.availability+.05)/.20)
        coverage=cv2.resize(self.deposit,(96,54),interpolation=cv2.INTER_AREA)
        weights=memory.identity_small*available*(.25+memory.importance)
        weights*=1/(1+coverage*.12)
        if attention is not None:weights*=.45+attention
        if weights.sum()<.001:return
        self.detail_credit+=dt*(125+35*rms)*smoothstep(phase/.30)
        count=int(self.detail_credit);self.detail_credit-=count
        weights=weights.ravel()/weights.sum()
        for loc in self.rng.choice(len(weights),count,p=weights):
            x=int(np.clip((loc%96+self.rng.random())*self.w/96,0,self.w-1))
            y=int(np.clip((loc//96+self.rng.random())*self.h/54,0,self.h-1))
            if memory.identity[y,x]<.15:continue
            scale=self.w/960
            radius=self.rng.uniform(2.2,4.8)*scale
            length=self.rng.uniform(4.,10.)*scale
            self.stroke(memory,x,y,radius,length,.48,3,phase,
                        duration=self.rng.uniform(3.,6.),identity=True)
            self.identity_strokes+=1

    def apply_ink(self,bounds,ink,color,direction):
        left,top,right,bottom=bounds
        region=self.canvas[top:bottom,left:right]
        region+=(color-region)*ink[:,:,None]
        self.direction[top:bottom,left:right]=(1-ink[:,:,None])*self.direction[top:bottom,left:right]+ink[:,:,None]*direction
        self.deposit[top:bottom,left:right]+=ink

    def advance_wet_strokes(self,dt):
        remaining=[]
        for mark in self.wet_strokes:
            previous=mark['age']/mark['duration']
            mark['age']=min(mark['duration'],mark['age']+dt)
            progress=mark['age']/mark['duration']
            if mark.get('identity',False):
                # Small local folds develop as a slow density change. Avoid a
                # per-frame geometric crop for these few-pixel regions.
                amount=progress*progress*(3-2*progress)-previous*previous*(3-2*previous)
                self.apply_ink(mark['bounds'],mark['ink']*amount,mark['color'],mark['direction'])
                if progress<1:remaining.append(mark)
                continue
            # Only the moving growth front changes this frame. Crop the cached
            # mark to it, rather than repeatedly process its entire empty ROI.
            u0,u1=previous*1.4-.28,progress*1.4-.12
            corners=np.array([mark['origin']+u*mark['length']*mark['tangent']+v*mark['normal']
                              for u in (u0,u1) for v in (-mark['spread'],mark['spread'])])
            left,top,right,bottom=mark['bounds']
            x0=max(left,int(corners[:,0].min())-2);x1=min(right,int(corners[:,0].max())+3)
            y0=max(top,int(corners[:,1].min())-2);y1=min(bottom,int(corners[:,1].max())+3)
            if x1<=x0 or y1<=y0:
                if progress<1:remaining.append(mark)
                continue
            crop=(slice(y0-top,y1-top),slice(x0-left,x1-left))
            u=mark['projection'][crop]
            before=smoothstep((previous*1.4-.2-u)/.16+.5)
            after=smoothstep((progress*1.4-.2-u)/.16+.5)
            self.apply_ink((x0,y0,x1,y1),mark['ink'][crop]*(after-before),mark['color'],mark['direction'])
            if progress<1:remaining.append(mark)
        self.wet_strokes=remaining

    def step(self,memory,phase,seconds,dt,rms,onset,transition=False,
             *,rate_scale=1.,attention=None,background_attention=None,slow=False):
        # Coarse washes -> body strokes -> smaller, still visible, pigment marks.
        phase=min(phase,.86) if self.soft else phase
        level=0 if phase<.22 else (1 if phase<.62 else 2)
        width_scale=self.w/960
        radius=(38*(1-phase)**1.6+4.0)*width_scale
        length=(92*(1-phase)**1.15+18)*width_scale
        hesitation=1-.16*memory.intensity*(.5+.5*np.sin(seconds*2.1))
        rate=(300+220*smoothstep(phase*2))*(.82+.30*rms)*hesitation*rate_scale
        self.credit+=rate*dt
        number=int(self.credit);self.credit-=number
        current=cv2.resize(self.canvas,(96,54),interpolation=cv2.INTER_AREA)
        error=np.mean(np.abs(current-memory.small_ref),axis=2)
        available=smoothstep((phase-memory.availability)/.16)
        if attention is None:
            weights=(error+.018)*memory.importance*available+.000005
        else:
            # Evolving forms and accumulated paint bias activation; no pixel error fitness.
            coverage=cv2.resize(self.deposit,(96,54),interpolation=cv2.INTER_AREA)
            regional=attention if background_attention is None else background_attention
            weights=memory.importance*(.06+1/(1+coverage*.30))*(.45+regional)*available+.000005
        weights=weights.ravel();weights/=weights.sum()
        locations=self.rng.choice(len(weights),number,p=weights)
        for loc in locations:
            x=int(np.clip((loc%96+self.rng.random())*self.w/96,0,self.w-1))
            y=int(np.clip((loc//96+self.rng.random())*self.h/54,0,self.h-1))
            self.stroke(memory,x,y,radius*self.rng.uniform(.72,1.25),length*self.rng.uniform(.7,1.2),
                        (.30+.35*phase)*(.9+.15*rms),level,phase,
                        duration=self.rng.uniform(2.8,4.8) if slow and self.soft else (self.rng.uniform(1.0,2.2) if slow else 0.))
        if slow and self.soft:self.develop_identity(memory,phase,dt,rms,attention)
        # Wet pigment gently disperses; existing paint is carried into the next scene.
        if transition:
            flow=np.sin(self.yy/self.h*5+seconds*.35)*(.008 if slow else .075)
            self.canvas=cv2.remap(self.canvas,self.xx+flow,self.yy+np.cos(self.xx/self.w*4)*(.004 if slow else .04),
                                 cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
            if int(seconds*30)%3==0:
                self.canvas=self.canvas*.985+cv2.GaussianBlur(self.canvas,(0,0),1.3)*.015
        self.advance_wet_strokes(dt)

    def frame(self):
        # Restrained light bleeding belongs to the pigment, not a separate overlay.
        light=np.maximum(self.canvas-.44,0)
        bloom=cv2.GaussianBlur(light,(0,0),5)*.14
        surface=self.canvas+bloom
        if self.soft:surface=cv2.GaussianBlur(surface,(0,0),1.2)
        return (np.clip(surface,0,1)*255).astype('uint8')
