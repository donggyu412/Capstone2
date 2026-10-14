"""Four-scene constructive dream, or a normal-speed window of the same state."""
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw
from team4.DreamModel.runtime.input_loader import load_inputs
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary
from team4.DreamModel.runtime.audio_analyzer import AudioAnalyzer
from team4.DreamModel.runtime.dream_surfaces import build_templates,DreamSurfaces
from team4.DreamModel.runtime.dream_world import DreamWorld
from team4.DreamModel.runtime.dream_score import DreamScore
from team4.DreamModel.runtime.media import VideoWriter
from team4.DreamModel.runtime.media import prepare_audio
from team4.DreamModel.runtime.provenance import file_digest, code_records


def prepare(config,audio_path=None,**flags):
    cv2.setNumThreads(1)
    bundle=load_inputs(config.input_root,audio_path)
    plans=[SemanticLibrary(config.semantic_config).plan(s) for s in bundle.scenes]
    audio=AudioAnalyzer(bundle.audio_path)
    templates,sources,layout=build_templates(bundle,plans,config.seed)
    if config.conditioning_off:flags[config.conditioning_off]=False
    world=DreamWorld(bundle.scenes,plans,templates,config.seed,config.audience,**flags)
    score=DreamScore(bundle.scenes,audio)
    world.score=score
    renderer=DreamSurfaces(templates,config.width,config.height,score,config.seed)
    return bundle,plans,audio,templates,sources,layout,world,score,renderer


def render(config,audio_path=None):
    started=time.perf_counter()
    start=config.preview_start_seconds or 0.;duration=config.preview_seconds or 300.
    if config.scene_seconds!=75 or start+duration>300.001:
        raise ValueError('Dream timeline requires original four 75-second scenes; window must fit 0–300s.')
    if not config.smoke and (config.width,config.height,config.fps,start,duration)!=(1920,1080,30,0,300):
        raise ValueError('Final requires 1920x1080,30fps,300seconds.')
    bundle,plans,audio,templates,sources,layout,world,score,renderer=prepare(config,audio_path)
    if bundle.audio_path is None:raise ValueError('A received soundtrack is required. Supply --audio <file>.')
    if audio.duration+1/30<start+duration:raise ValueError('Received soundtrack is shorter than the requested original-clock window.')
    config.output_path.parent.mkdir(parents=True,exist_ok=True)
    config.report_path.parent.mkdir(parents=True,exist_ok=True)
    if config.output_path.exists():raise ValueError(f'Output exists; choose a new output path to preserve prior results: {config.output_path}')
    if start==0 and duration==300:
        clip=bundle.audio_path;timing={'source_window':[0,300],'playback_rate':1.,'source_modified':False}
    else:
        clip,timing=prepare_audio(bundle.audio_path,config.output_path.with_name(config.output_path.stem+'_audio.wav'),start,duration)
    first=round(start*30);end=round((start+duration)*30);count=end-first
    sample_times=([0,10,20,35,55,68,75,84,100,115,138,145,150,160,185,208,220,225,240,255,275,289,297,299.9667]
                  if duration==300 else list(np.linspace(start,start+duration-1/30,8)))
    wanted={round(t*30) for t in sample_times};captures=[];samples=[];changes=[];previous=None
    digest=hashlib.sha256();last_notice=time.perf_counter()
    code_hashes=code_records([Path(__file__)])
    with VideoWriter(config.output_path,config.width,config.height,30,audio_path=clip,expected_frames=count,
                     crf=18,keyframe_interval=300) as writer:
        for f in range(end):
            t=f/30;world.step(t,1/30,*audio.features(t))
            if f>=first:
                pixels=renderer.render(world);writer.write(pixels);digest.update(pixels.tobytes())
                small=cv2.resize(pixels,(160,90),interpolation=cv2.INTER_AREA).astype('float32')
                if previous is not None:changes.append(float(np.mean(np.abs(small-previous))))
                previous=small
                if f%30==0 or f==end-1:samples.append({**world.snapshot(),'renderer':renderer.stats})
                if f in wanted:captures.append((t,Image.fromarray(pixels).resize((480,270))))
            if time.perf_counter()-last_notice>12 or f==end-1:
                elapsed=time.perf_counter()-started
                print(f'[dream] source {t:.2f}/300s; output {max(0,f-first+1)}/{count} frames; elapsed {elapsed:.1f}s',flush=True)
                last_notice=time.perf_counter()
    report={'model':'DreamModel collective dream animation','scope':'background and objects; distinct generative engines',
        'output_file':str(config.output_path),'resolution':[config.width,config.height],'fps':30,'frames':count,
        'duration_seconds':count/30,'source_window':[start,start+duration],'playback_rate':1.,'scene_seconds':75,
        'nominal_scene_starts':[0,75,150,225],'transition_growth_starts':[65,140,215],
        'methods':{'background':'adaptive irregular-region graph diffusion/reaction/deposition; finite spatial growth',
                   'objects':'connected control-graph structural mutation, recombination, selection and quality-diversity archive',
                   'shared_render':'source-derived growing regional surfaces, no source-image/PNG plate compositing'},
        'flags':world.flags,'seed':config.seed,'story_plans':[p.as_report() for p in plans],
        'law_map':score.report(),'evolution_events':world.evolution.events,'memory_inheritance':world.inheritance,
        'audience':{**config.audience.report(),'mode':'SIMULATION','measured_aggregate_supplied':False},
        'layout':layout,'audio':{**audio.as_report(),'timeline':timing},'samples':samples,
        'input_files':[{'path':str(p),'sha256':file_digest(p)} for p in dict.fromkeys([*bundle.input_files,*sources,bundle.audio_path])],
        'code_files':code_hashes,'raw_frames_sha256':digest.hexdigest(),
        'frame_change':{'sample_size':[160,90],'mean':float(np.mean(changes)),'maximum':max(changes)},
        'elapsed_seconds':time.perf_counter()-started,
        'limitations':['finite source-conditioned development, not unlimited OEE',
            'audience conditions are SIMULATION; no measured collective affect supplied',
            'object layout is an explicit artistic assumption, not an upstream approved placement',
            'some provided object images are stylized folded forms; law effects are visual interpretations',
            'latest Team3 animated MP4s not locally supplied; no direct video comparison claimed']}
    config.report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(480*4,294*math_ceil_div(len(captures),4)),(15,20,24));draw=ImageDraw.Draw(sheet)
    for i,(t,img) in enumerate(captures):
        x=(i%4)*480;y=(i//4)*294;sheet.paste(img,(x,y));draw.text((x+8,y+274),f'{t:.2f} s',fill='white')
    sheet.save(config.output_path.with_name(config.output_path.stem+'_contact.jpg'),quality=93)
    print(f'[complete] {config.output_path}',flush=True)
    return report


def math_ceil_div(n,d):return (n+d-1)//d
