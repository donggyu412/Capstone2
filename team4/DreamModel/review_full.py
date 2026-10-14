"""Sample the entire original clock before full encoding; no time compression."""
from pathlib import Path
from dataclasses import replace
from time import perf_counter
import argparse,json
from PIL import Image,ImageDraw
from .config import RenderConfig
from .dream_pipeline import prepare


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audio',type=Path,required=True)
    args=parser.parse_args();out=Path(__file__).parent/'output/full_review'
    out.mkdir(parents=True,exist_ok=True);c=replace(RenderConfig(),width=640,height=360)
    t0=perf_counter();b,p,a,templates,src,layout,w,score,r=prepare(c,args.audio)
    print('prepared',perf_counter()-t0,'unsupported',score.unsupported,flush=True)
    times=[0,10,20,35,55,68,75,84,100,115,138,145,150,160,185,208,220,225,240,255,275,289,297,299.9667]
    frames={round(t*30):t for t in times}
    sheet=Image.new('RGB',(1280,6*200));d=ImageDraw.Draw(sheet);i=0;stats=[]
    for f in range(9000):
        w.step(f/30,1/30,*a.features(f/30))
        if f in frames:
            st=perf_counter();pixels=r.render(w)
            print('sample',f/30,'render',round(perf_counter()-st,3),flush=True)
            im=Image.fromarray(pixels);im.save(out/f'frame_{f:04}.jpg',quality=95)
            x=(i%4)*320;y=(i//4)*200;sheet.paste(im.resize((320,180)),(x,y))
            d.text((x+4,y+183),str(round(f/30,2))+'s',fill='white');i+=1
            stats.append({**w.snapshot(),'render':r.stats})
    sheet.save(out/'full_timeline_contact.jpg',quality=94)
    (out/'timeline_samples.json').write_text(json.dumps({'samples':stats,'inheritance':w.inheritance,
        'events':score.report(),'evolution':w.evolution.events},ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',perf_counter()-t0,flush=True)


if __name__=='__main__':main()
