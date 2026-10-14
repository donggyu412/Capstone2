"""Three matched layer previews, all four scenes, original-speed review excerpts."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import argparse,json,time,wave,hashlib
import cv2,numpy as np
from PIL import Image,ImageDraw
from .config import RenderConfig
from .dream_pipeline import prepare
from .frame_renderer import VideoWriter
from .run_report import file_digest


WINDOWS=((0,20),(30,45),(70,90),(155,170),(235,250))


def review_audio(source,destination):
    timeline=[];position=0.
    with wave.open(str(source),'rb') as inp,wave.open(str(destination),'wb') as out:
        if inp.getsampwidth()!=2:raise ValueError('Review WAV adapter requires supplied 16-bit PCM audio')
        out.setparams(inp.getparams());rate=inp.getframerate();channels=inp.getnchannels()
        for start,end in WINDOWS:
            inp.setpos(round(start*rate));samples=np.frombuffer(inp.readframes(round((end-start)*rate)),dtype='<i2').copy().reshape(-1,channels)
            expected=round((end-start)*rate)
            if len(samples)!=expected:raise ValueError('Source audio is too short for review windows')
            fade=round(.02*rate)
            samples[:fade]=(samples[:fade]*np.linspace(0,1,fade)[:,None]).astype('<i2')
            samples[-fade:]=(samples[-fade:]*np.linspace(1,0,fade)[:,None]).astype('<i2')
            out.writeframes(samples.tobytes())
            timeline.append({'source':[start,end],'preview':[position,position+end-start],'playback_rate':1.})
            position+=end-start
    return timeline


def render(audio_path,output):
    output.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    config=replace(RenderConfig(),width=960,height=540,smoke=True)
    b,plans,a,templates,sources,layout,w,score,r=prepare(config,audio_path)
    clip=output/'review_sound.wav';audio_windows=review_audio(b.audio_path,clip)
    names={'background':'01_background_preview.mp4','objects':'02_object_preview.mp4','integrated':'03_integrated_preview.mp4'}
    expected=round(sum(end-start for start,end in WINDOWS)*30)
    code_names=('background_openended.py','dream_world.py','dream_surfaces.py','dream_score.py','urgent_previews.py',
        'input_loader.py','semantic_conditioning.py','semantic_config.json','assumed_layout.json','audio_analyzer.py','frame_renderer.py')
    code_hashes=[{'path':str(Path(__file__).with_name(n)),'sha256':file_digest(Path(__file__).with_name(n))} for n in code_names]
    input_hashes=[{'path':str(p),'sha256':file_digest(p)} for p in dict.fromkeys([*b.input_files,*sources,b.audio_path])]
    samples=[];captures={k:[] for k in names};digests={k:hashlib.sha256() for k in names};count=0;last=time.perf_counter()
    wanted={0,300,599,900,1125,1349,2100,2250,2550,2699,4650,4950,5099,7050,7350,7499}
    with ExitStack() as stack:
        writers={k:stack.enter_context(VideoWriter(output/v,960,540,30,audio_path=clip,expected_frames=expected,crf=18,keyframe_interval=300)) for k,v in names.items()}
        for f in range(round(WINDOWS[-1][1]*30)):
            t=f/30;w.step(t,1/30,*a.features(t))
            if any(start<=t<end for start,end in WINDOWS):
                frames=r.render(w,separate=True)
                for k,frame in frames.items():
                    writers[k].write(frame);digests[k].update(frame.tobytes())
                    if f in wanted:captures[k].append((t,count/30,Image.fromarray(frame).resize((480,270))))
                if count%30==0 or count==expected-1:
                    samples.append({**w.snapshot(),'preview_seconds':count/30,'renderer':r.stats,
                        'backgrounds':{str(i+1):{'parameters':s['space'].genes.tolist(),
                            'scale_mass':s['space'].mass.mean(1).tolist(),'surface_material':float(s['space'].material.mean()),
                            'declining_region_seconds':s['space'].extinction.tolist(),
                            'dominance_changes':s['space'].dominance_changes} for i,s in w.active()}})
                count+=1
            if time.perf_counter()-last>15:
                print(f'[3 previews] source {t:.1f}s; {count}/{expected} frames each; elapsed {time.perf_counter()-started:.0f}s',flush=True)
                last=time.perf_counter()
    assert count==expected
    for k,images in captures.items():
        sheet=Image.new('RGB',(1920,294*((len(images)+3)//4)),(14,18,22));d=ImageDraw.Draw(sheet)
        for i,(t,pt,image) in enumerate(images):
            x=i%4*480;y=i//4*294;sheet.paste(image,(x,y));d.text((x+5,y+275),f'source {t:.2f}s / preview {pt:.2f}s',fill='white')
        sheet.save(output/(k+'_contact.jpg'),quality=94)
    report={'status':'preview review required; final 300-second render remains blocked by latest user instruction',
        'files':{k:str(output/v) for k,v in names.items()},'resolution':[960,540],'fps':30,'frames_per_video':count,
        'duration_per_video':count/30,'source_scene_seconds':75,'rendered_scene_ids':[1,2,3,4],
        'review_windows':audio_windows,'editing_note':'Original-speed excerpts with explicit review cuts; not a shortened story timeline or accelerated playback',
        'audio':{**a.as_report(),'preview_wav':str(clip),'cut_edge_fade_seconds':.02},
        'background_engines':{str(i+1):s['space'].report() for i,s in w.states.items()},
        'object_evolution':w.evolution.events,'inheritance':w.inheritance,'story':score.report(),
        'audience':{**config.audience.report(),'mode':'SIMULATION','measured_aggregate_supplied':False},
        'layout':layout,'input_files':input_hashes,'code_files':code_hashes,'samples':samples,
        'raw_frame_hashes':{k:d.hexdigest() for k,d in digests.items()},'elapsed_seconds':time.perf_counter()-started,
        'limits':['finite source-conditioned grammar, no claim of unbounded OEE',
            'continuous activator/inhibitor RD; Gray-Scott equation is not implemented',
            'competition decline/regrowth is measured; complete local scale extinction must be checked separately',
            'object recombination acts on control graphs; physical collision/fusion of two complete objects is not simulated',
            'visual acceptance requires user review']}
    (output/'preview_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[complete] '+str(output),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path(__file__).parent/'output/urgent_revision/review_v1')
    args=p.parse_args();render(args.audio.resolve(),args.output.resolve())
