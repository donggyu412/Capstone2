"""Visual directions traceable to the supplied story, on an uncompressed clock.

These are authored interpretations. A sound-energy onset is not recognized as a
specific crack/drop; the received soundtrack is never resynthesized to fit a law.
"""
import math
import numpy as np
from team4.DreamModel.runtime.math_utils import ease
from team4.DreamModel.runtime.story_rules import RULES


EXTRA_RULES=(
 (3,('손끝','무게'),'weightless',184,198,'connected file surfaces lift after the figure approaches'),
 (3,('종이','회전'),'paper_orbit',185,212,'paper control surfaces rotate and translate as a connected form'),
 (3,('재처럼','바스러'),'ash',207,222,'paper regions contract and settle, then become crack-growth memory'),
 (3,('조각','금'),'crack',206,224,'falling paper fragments seed branching floor fissures'),
 (3,('팔','늘어'),'elongate',190,220,'arm-region control distances lengthen while the torso is retained'),
 (4,('소리','먼저'),'sound_leads',248,258,'source energy onset precedes file descent; acoustic proxy'),
 (4,('페이지','변'),'pages',248,281,'edge-fold count moves through 32, 27 and 40'),
 (4,('타일','전에'),'anticipatory_crack',251,270,'floor fissure grows before the reaching hand arrives'),
)


class DreamScore:
    def __init__(self,scenes,audio):
        self.events={};self.unsupported=[]
        for scene in scenes:
            for law in scene.physics_laws:
                r=next((r for r in (*RULES,*EXTRA_RULES) if r[0]==scene.scene_id and all(k in law for k in r[1])),None)
                if r:self.events[r[2]]={'scene':scene.scene_id,'law':law,'start':r[3],'end':r[4],'interpretation':r[5]}
                else:self.unsupported.append({'scene':scene.scene_id,'law':law})
        self.scenes=scenes;self.audio=audio
        # Select an actually observed source-envelope change. This is an acoustic
        # proxy, not a fabricated sound cue or a claim to identify a crack.
        ts=np.arange(246,253,.05)
        self.sound_cue=float(ts[np.argmax([audio.features(float(t))[1] for t in ts])])
        if 'sound_leads' in self.events:
            self.events['sound_leads']['source_energy_cue']=self.sound_cue
            self.events['sound_leads']['motion_start']=self.sound_cue+1.8

    def p(self,key,t,enabled=True):
        e=self.events.get(key)
        return float(ease((t-e['start'])/(e['end']-e['start']))) if e and enabled else 0.

    def warp(self,points,kind,sid,world):
        p=points.copy();t=world.time;enabled=world.flags['story']
        if not enabled:return p
        phase=(t-sid*75)
        if sid==0:
            if kind=='space':
                amount=.065*self.p('recede',t)+.008*world.audio[0]*self.p('audio_space',t)
                p[:,0]=.54+(p[:,0]-.54)*(1+amount*(.25+np.abs(p[:,1]-.54)))
                p[:,1]+=(p[:,1]-.55)*amount*.4
            if kind=='figure':
                reach=float(ease((t-49)/18))
                arms=np.clip((p[:,1]-.40)/.30,0,1)
                p[:,0]-=.10*reach*arms;p[:,1]+=.07*reach*arms
                p[:,1]-=.003*np.sin(t*.33)*self.p('float',t)
            if kind=='journal':
                q=self.p('page_turn',t);right=np.maximum(p[:,0]-.325,0)
                p[:,0]-=right*(1-math.cos(q*math.pi))*.62
                p[:,1]-=np.sin(q*math.pi)*right*.40
        elif sid==1:
            if kind=='droplet':
                cycle=(phase+10)%9/9
                p[:,1]+=.37*float(ease(cycle))
            if kind=='figure':
                p[:,0]-=.065*self.p('glide',t)
                hand=np.clip((p[:,1]-.5)/.25,0,1)
                p[:,1]+=.095*hand*self.p('hand_pool',t)
            if kind=='record':
                q=self.p('flutter',t);free=np.clip((p[:,0]-.19)/.16,0,1)
                p[:,0]+=.015*np.sin((t-96)*.6)*q*free
                p[:,1]+=.013*np.sin((t-96)*.6+.8)*q*free
                drop=self.p('erase_before_water',t)
                p[:,0]+=.14*drop;p[:,1]+=.19*drop
            if kind=='pool':p[:,1]=.875+(p[:,1]-.875)*(1+.60*self.p('hand_pool',t))
        elif sid==2:
            if kind=='record':p[:,1]-=.12*self.p('weightless',t)
            if kind=='paper':
                q=self.p('paper_orbit',t);angle=q*.48
                c=np.array([.475,.47]);mat=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
                p=c+(p-c)@mat;p[:,0]+=.065*q;p[:,1]-=.03*np.sin(q*math.pi)
                p[:,1]+=.30*self.p('ash',t)
            if kind=='figure':
                limbs=np.clip(np.abs(p[:,0]-.72)/.12,0,1)*np.clip((p[:,1]-.4)/.3,0,1)
                p[:,0]+=(p[:,0]-.72)*.35*self.p('elongate',t)*limbs
                p[:,1]+=.06*self.p('elongate',t)*limbs
        elif sid==3:
            if kind=='record':
                fall=float(ease((t-(self.sound_cue+1.8))/7)) if 'sound_leads' in self.events else 0
                p[:,1]-=.15*(1-fall)
            if kind=='hand':
                reach=float(ease((t-248)/13));retreat=float(ease((t-279)/11))
                p[:,0]-=.16*reach*(1-retreat);p[:,1]+=.10*reach*(1-retreat)
            if kind=='space':p[:,1]+=.004*np.sin((t-287)*.8)*float(ease((t-287)/10))*np.clip((p[:,1]-.65)*3,0,1)
        return p

    def material_factor(self,kind,sid,world,index):
        if not world.flags['story']:return 1.
        t=world.time
        if kind=='paper' and sid==2:return 1-self.p('ash',t)*( .85+.15*np.sin(index*1.7))
        if kind=='droplet' and sid==1:
            cycle=(t-65)%9/9
            return float(1-ease((cycle-.80)/.2))
        return 1.

    def report(self):
        return {'events':self.events,'unsupported':self.unsupported,
            'timing':'artistic placement inside original 75-second scenes, no source time stretching',
            'scope':'geometric interpretations; not literal physical reconstruction of every sentence',
            'source_audio_cue_seconds':self.sound_cue,
            'audio_limit':'amplitude/onset proxy, no specific sound-source recognition; original waveform preserved'}
