"""Encode four continuous-state segments concurrently, then mux original audio.

Each worker starts from a serialized state immediately before its first frame.
No scene reset, playback acceleration, missing intermediate frames, or upscale.
"""
import json,pickle,time,subprocess,hashlib
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,wait
import cv2,numpy as np
from .dream_pipeline import prepare
from .dream_surfaces import DreamSurfaces
from .frame_renderer import VideoWriter,find_ffmpeg,subprocess_options
from .run_report import file_digest


def encode_segment(snapshot_path):
    cv2.setNumThreads(1)
    with open(snapshot_path,'rb') as f:world,config,start,end=pickle.load(f)
    index=start//2250;folder=Path(snapshot_path).parent
    output=folder/f'part_{index+1:02}.mp4';progress=folder/f'part_{index+1:02}_progress.json'
    renderer=DreamSurfaces(world.templates,config.width,config.height,world.score,config.seed)
    samples=[];last=time.perf_counter();started=last;digest=hashlib.sha256();deltas=[];previous=None
    with VideoWriter(output,config.width,config.height,30,expected_frames=end-start,crf=18,keyframe_interval=300) as writer:
        for frame in range(start,end):
            t=frame/30;world.step(t,1/30,*world.score.audio.features(t))
            pixels=renderer.render(world);writer.write(pixels);digest.update(pixels.tobytes())
            small=cv2.resize(pixels,(160,90),interpolation=cv2.INTER_AREA).astype('float32')
            if previous is not None:deltas.append(float(np.abs(small-previous).mean()))
            previous=small
            if frame%30==0 or frame==end-1:samples.append({**world.snapshot(),'renderer':renderer.stats})
            if time.perf_counter()-last>10 or frame==end-1:
                progress.write_text(json.dumps({'done':frame-start+1,'total':end-start,'source_seconds':t,
                    'elapsed':time.perf_counter()-started}),encoding='utf-8');last=time.perf_counter()
    report={'source_frames':[start,end],'frames':end-start,'raw_sha256':digest.hexdigest(),'samples':samples,
            'frame_change':{'mean':float(np.mean(deltas)),'maximum':max(deltas)},'elapsed':time.perf_counter()-started}
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return str(output)


def render(config,audio_path,*,workers=2):
    if (config.width,config.height,config.fps,config.scene_seconds,config.scene_count)!=(1920,1080,30,75,4):
        raise ValueError('Final renderer requires 1920x1080,30fps,4x75seconds.')
    if config.output_path.exists():raise ValueError('Final path already exists; use --output with a new filename.')
    started=time.perf_counter()
    bundle,plans,audio,templates,sources,layout,world,score,_=prepare(config,audio_path)
    if audio.duration<300-1/30:raise ValueError('A received 300-second soundtrack is required.')
    config.output_path.parent.mkdir(parents=True,exist_ok=True)
    config.report_path.parent.mkdir(parents=True,exist_ok=True)
    build=config.output_path.parent/(config.output_path.stem+'_build')
    build.mkdir(exist_ok=False)
    code_names=('render_final.py','dream_pipeline.py','dream_world.py','background_openended.py','dream_surfaces.py','dream_score.py','emergence_renderer.py','developmental_world.py',
        'input_loader.py','semantic_conditioning.py','semantic_config.json','assumed_layout.json',
        'audience.py','audio_analyzer.py','frame_renderer.py','config.py','main.py')
    code_hashes=[{'path':str(Path(__file__).with_name(n)),'sha256':file_digest(Path(__file__).with_name(n))} for n in code_names]
    inputs=[{'path':str(p),'sha256':file_digest(p)} for p in dict.fromkeys([*bundle.input_files,*sources,bundle.audio_path])]
    snapshots=[]
    for frame in range(9000):
        if frame%2250==0:
            p=build/f'state_{frame:04}.pkl'
            with p.open('wb') as f:pickle.dump((world,config,frame,frame+2250),f,pickle.HIGHEST_PROTOCOL)
            snapshots.append(p);print(f'[state] snapshot immediately before frame {frame}',flush=True)
        world.step(frame/30,1/30,*audio.features(frame/30))
    print(f'[render] {workers} workers; all 9000 native 1080p frames, continuous carried state',flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs=[pool.submit(encode_segment,str(p)) for p in snapshots];pending=set(jobs);last=0
        while pending:
            finished,pending=wait(pending,timeout=5)
            for job in finished:job.result()
            if time.perf_counter()-last>25 or not pending:
                progress=[]
                for i in range(4):
                    p=build/f'part_{i+1:02}_progress.json'
                    try:progress.append(json.loads(p.read_text(encoding='utf-8')).get('done',0))
                    except (OSError,json.JSONDecodeError):progress.append(0)
                print(f'[render] {sum(progress)}/9000 frames; parts {progress}; elapsed {time.perf_counter()-started:.0f}s',flush=True)
                last=time.perf_counter()
        outputs=[Path(job.result()) for job in jobs]
    listing=build/'concat.txt'
    listing.write_text('\n'.join(f"file '{p.name}'" for p in outputs),encoding='utf-8')
    temporary=config.output_path.with_name('.'+config.output_path.stem+'_mux.mp4')
    command=[find_ffmpeg(),'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),
             '-i',str(bundle.audio_path),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
             '-t','300','-movflags','+faststart',str(temporary)]
    result=subprocess.run(command,capture_output=True,**subprocess_options())
    if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace'))
    temporary.replace(config.output_path)
    parts=[json.loads(p.with_suffix('.json').read_text(encoding='utf-8')) for p in outputs]
    report={'model':'DreamModel — collective dream animation','output_file':str(config.output_path),
        'resolution':[1920,1080],'fps':30,'frames':9000,'duration_seconds':300,'playback_rate':1.,'scene_seconds':75,
        'nominal_scene_starts':[0,75,150,225],'transition_growth_starts':[65,140,215],
        'rendering':'4 native-resolution continuous-state segments; video stream-copy concatenation; original audio clock',
        'workers':workers,'final_render_authorized':'2026-10-08 user: 좋아 최종본 다 만들고 mp4를 바로 다운받게 세팅해놔',
        'methods':{'background':'memory-conditioned reaction/diffusion with evolutionary parameter search and multi-scale resource competition on irregular region adjacency graph',
                   'objects':'connected variable control graph mutation/recombination/fitness/novelty/diversity selection',
                   'integration':'shared growing material surfaces and inherited colour/roots/trace; no source plates'},
        'flags':world.flags,'seed':config.seed,'story_plans':[p.as_report() for p in plans],'law_map':score.report(),
        'background_engines':{str(i+1):s['space'].report() for i,s in world.states.items()},
        'evolution_events':world.evolution.events,'memory_inheritance':world.inheritance,
        'audience':{**config.audience.report(),'mode':'SIMULATION','measured_aggregate_supplied':False},
        'layout':layout,'audio':{**audio.as_report(),'source_window':[0,300],'playback_rate':1.,'source_modified':False},
        'input_files':inputs,'code_files':code_hashes,'samples':[s for p in parts for s in p['samples']],
        'parts':[{k:v for k,v in p.items() if k!='samples'} for p in parts],
        'elapsed_seconds':time.perf_counter()-started,
        'limitations':['finite source-conditioned grammar, not unlimited OEE',
            'artistic activator/inhibitor reaction-diffusion, not exact Gray-Scott',
            'object combination uses control-graph recombination, not whole-object physical collision/fusion',
            'SIMULATION audience conditions; no measured collective data supplied',
            'assumed layout, not upstream-approved coordinates',
            'stylized source objects and qualitative physics-law interpretations',
            'latest Team3 MP4s unavailable locally; no direct comparison claimed']}
    config.report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'[complete] {config.output_path}',flush=True)
    return report
