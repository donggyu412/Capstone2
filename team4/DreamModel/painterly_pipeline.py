"""Original-speed memory emergence; encode only seconds 65 through 85.

The historical module name is retained for imports. Active rendering uses soft
material with no bristle texture, not a fixed painting style.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import time
import wave
import cv2
import numpy as np
from .audio_analyzer import AudioAnalyzer
from .brush_painter import BrushMemory,BrushPainter
from .config import REPO_ROOT,RenderConfig
from .frame_renderer import VideoWriter,find_ffmpeg,subprocess_options,load_background
from .input_loader import load_inputs
from .run_report import file_digest
from .scene_composition import build_composition
from .semantic_conditioning import SemanticLibrary
from .evolving_brush import EvolvingBrush,align_memory


def prepare_audio(source,destination,start=65.,duration=20.):
    if source is None:return None,{'status':'no supplied audio'}
    rate=44100
    command=[find_ffmpeg(),'-hide_banner','-loglevel','error','-ss',str(start),'-i',str(source),
             '-t',str(duration),'-ac','2','-ar',str(rate),'-f','f32le','pipe:1']
    result=subprocess.run(command,capture_output=True,**subprocess_options())
    if result.returncode:raise ValueError(result.stderr.decode('utf-8',errors='replace'))
    samples=np.frombuffer(result.stdout,dtype='<f4').reshape(-1,2)
    if len(samples)<round(duration*rate):raise ValueError('Audio is shorter than the requested original-time window')
    samples=samples[:round(duration*rate)].copy()
    fade=round(.02*rate)
    samples[:fade]*=np.linspace(0,1,fade)[:,None];samples[-fade:]*=np.linspace(1,0,fade)[:,None]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(destination),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(rate)
        out.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())
    return destination,{'source':str(source),'source_start':start,'source_end':start+duration,
        'playback_rate':1.,'time_stretch':False,'scene_splice':False,'edge_fade_seconds':.02}


def build_memories(config,bundle):
    library=SemanticLibrary(config.semantic_config)
    memories=[];fields=[];sources=[];layouts=[]
    for scene in bundle.scenes[:2]:
        original=REPO_ROOT/'team3/background/input/storyboard'/f'scene_{scene.scene_id:02d}.png'
        if not original.is_file():raise ValueError(f'Missing spatial memory reference: {original}')
        plate=load_background(original,config.width,config.height).astype('float32')/255
        delivered=load_background(scene.background_path,config.width,config.height).astype('float32')/255
        plate=plate*.90+cv2.GaussianBlur(delivered,(0,0),8)*.10
        placements={'journal':(.28,.77,.27,1.05,-8),'pool':(.56,.86,.075,3.0,0),
                    'figure':(.63 if scene.scene_id==1 else .55,.47,.40,1.0,0),
                    'record':(.34,.79,.22,1.2,-11),'droplet':(.52,.40,.045,.7,0)}
        composition=build_composition(scene,config.width,config.height,library,placements,
                                      (np.clip(plate,0,1)*255).astype('uint8'))
        memories.append(BrushMemory(composition,config.seed+scene.scene_id,soft=True))
        fields.append(align_memory(scene,composition,library,original,config.width,config.height))
        layouts.append(composition.layout)
        sources.extend([original,scene.background_path,*[o.path for o in scene.objects]])
    return memories,fields,sources,layouts


def render(config:RenderConfig,audio_path:Path|None=None):
    if not config.smoke:raise ValueError('This revision is a transition preview only; --final is disabled.')
    if (config.scene_count,config.scene_seconds,config.preview_start_seconds,config.preview_seconds)!=(2,75,65,20):
        raise ValueError('Preview requires two 75-second scenes, capturing exactly original seconds 65–85.')
    cv2.setNumThreads(1);started=time.perf_counter()
    bundle=load_inputs(config.input_root,audio_path)
    memories,fields,sources,layouts=build_memories(config,bundle)
    audio_file,audio_timing=prepare_audio(bundle.audio_path,
        config.output_path.with_name(config.output_path.stem+'_audio.wav'))
    # Warm-up and captured frames both use the original 300-second audio clock.
    audio=AudioAnalyzer(bundle.audio_path)
    surface=BrushPainter(config.width,config.height,config.seed,soft=True)
    evolution=EvolvingBrush(fields,config.seed,config.audience)
    state_hash=hashlib.sha256();samples=[];inheritance=None
    nominal_boundary=75.
    overlap_start=nominal_boundary-config.transition_seconds/2
    start_frame=round(config.preview_start_seconds*30)
    end_frame=start_frame+config.total_frames
    active_index=0
    with VideoWriter(config.output_path,config.width,config.height,30,
                     audio_path=audio_file,expected_frames=config.total_frames) as writer:
        for frame in range(end_frame):
            original_time=frame/30
            if original_time>=overlap_start and active_index==0:
                before=hashlib.sha256(surface.canvas.tobytes()).hexdigest()
                active_index=1;surface.inherit();evolution.enter_scene(1)
                inheritance={'original_seconds':original_time,'canvas_before':before,
                    'canvas_after':hashlib.sha256(surface.canvas.tobytes()).hexdigest(),
                    'wet_forms_preserved':len(surface.wet_strokes),'inherited_marks':surface.total_strokes}
            local_time=original_time if active_index==0 else original_time-overlap_start
            phase=local_time/75
            rms,onset=audio.features(original_time)
            evolution.step(phase,1/30,rms,onset)
            memory=memories[active_index]
            surface.step(memory,phase,local_time,1/30,rms,onset,
                transition=active_index==1 and original_time<85,
                rate_scale=1/7.5,attention=evolution.attention,
                background_attention=evolution.background.field,slow=True)
            evolution.paint(surface,memory,phase,1/30,rms)
            if frame>=start_frame:
                pixels=surface.frame();writer.write(pixels);state_hash.update(pixels.tobytes())
                if (frame-start_frame)%30==0 or frame==end_frame-1:
                    samples.append({'preview_seconds':(frame-start_frame)/30,'original_seconds':original_time,
                        'forms':len(surface.wet_strokes),'marks':surface.total_strokes,
                        'rms':rms,'evolution':evolution.engine.snapshot()})
            if frame%450==0:
                print(f'[state] original {original_time:.0f}s; '+('warm-up only' if frame<start_frame else 'capturing preview'),flush=True)
    evo=evolution.report()
    window_events=[e for e in evo['events'] if 65<=e['original_seconds']<85]
    evo['preview_event_counts']=dict(Counter(e['type'] for e in window_events))
    inputs=[config.input_root/'storyboard/scenes.json',config.input_root/'storyboard/dream_scenes.json',
            config.input_root/'objects/objects.json',*sources]
    if bundle.audio_path:inputs.append(bundle.audio_path)
    report={'model':'DreamModel memory emergence','purpose':'What does an AI dream after experiencing human emotion and memory?',
        'status':'bounded evolving-form prototype; not proof of unrestricted open-endedness',
        'resolution':[config.width,config.height],'fps':30,'duration':20,'total_frames':600,
        'scene_count':2,'original_scene_seconds':75,'original_window':[65,85],'nominal_scene_boundary':75,
        'overlap_window':[overlap_start,nominal_boundary+config.transition_seconds/2],
        'playback_rate':1.,'simulation_dt_seconds':1/30,'warm_up_frames':start_frame,'encoded_original_frames':[start_frame,end_frame-1],
        'seed':config.seed,'inheritance':inheritance,'evolution':evo,'samples':samples,'layouts':layouts,
        'identity_material':{'local_detail_marks':surface.identity_strokes,
            'method':'Object-conditioned small material deposits on the same canvas; broad washes are restrained over growing identity. No sprite overlay.'},
        'audience_atmosphere':config.audience.report(),
        'audio':{**audio.as_report(),'timeline':audio_timing},
        'input_files':[{'path':str(p),'sha256':file_digest(p)} for p in inputs],
        'output_file':str(config.output_path),'raw_frames_sha256':state_hash.hexdigest(),
        'elapsed_seconds':time.perf_counter()-started,
        'visual_method':'Slow, soft regional emergence; no visible bristle texture or polygon drawing. Existing field persists.',
        'conditioning':{'story':'Memory salience changes organism births, fitness and regional emergence.',
            'emotion':'Input intensity biases structural mutation, selection pressure and persistence.',
            'sound':'Unspliced original RMS/onset modulate birth and recombination; no playback acceleration.',
            'memory':'Surviving graph nodes/lineage, pigment field and direction influence the incoming scene.'},
        'limits':['Finite source-derived visual grammar and population cap.',
            'Spatial references retain recognizability; generation remains memory-conditioned, not unrestricted invention.',
            'Object placement and equal 75-second source sections are declared artistic/alignment assumptions.',
            'No private Team2 vectors, no upstream changes, no final five-minute render.']}
    config.report_path.parent.mkdir(parents=True,exist_ok=True)
    config.report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'[complete] {config.output_path}',flush=True)
    return report
