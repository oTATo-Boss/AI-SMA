#!/usr/bin/env python3
"""Reproducible original sample films. No downloads, API calls or shared installs.

python render_samples.py --preview
python render_samples.py --all --allow-system-voice  # macOS private test only
python render_samples.py --film science --voice-dir ./licensed-voice

Other systems supply licensed speech WAVs named science-00.wav, drama1-00.wav,
etc.; captions and timing are generated from the same segment records.
"""
from __future__ import annotations
import argparse
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'outputs'
FPS = 30
RATE = 48000
PAPER = '#EEE8DB'
INK = '#192520'
GREEN = '#52755D'
RED = '#BC4F35'
GOLD = '#CC9C4A'
TAU = math.tau
SCIENCE = [
    '同一轮月亮，为什么每天看起来不一样？',
    '月亮自己不发光，我们看见的是反射的阳光。',
    '通常，太阳照亮月球朝向它的一半。',
    '月球绕着地球走，我们的观看角度也在变。',
    '新月时，朝向地球的这一面大多没有阳光。',
    '再过几天，亮面露出一条弯弯的边。',
    '上弦月，看起来像一张被分成两半的圆盘。',
    '满月时，朝向我们的这一面几乎全被照亮。',
    '日常月相，不是地球的影子把月亮挡住。',
    '从一次新月，到下一次，大约二十九点五天。',
    '地球挡住阳光时，发生的才是月食。',
    '月亮没有少一块，改变的是我们看见的亮面。',
]
DRAMA1 = [
    '雨停之前，桌上多了一张车票。',
    '左上角缺了一块，背面系着红线。',
    '离末班车，还有十分钟。',
    '背面只留了一句话：还给她。',
    '他把车票收好，推开了门。',
    '雨还没有停，有人仍在等。',
]
DRAMA2 = [
    '还是那张车票，还是那一截红线。',
    '南站，二十一点十分。',
    '长椅旁，一只手伸了过来。',
    '她拿出的缺角，刚好吻合。',
    '车票终于回到原来的主人手中。',
    '列车开走，长椅上留下了一句谢谢。',
]
SCRIPT = {'science': SCIENCE, 'drama1': DRAMA1, 'drama2': DRAMA2}
DURATIONS = {'science':60, 'ad':15, 'ad_vertical':15, 'drama1':30, 'drama2':30, 'mv':30}


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))


def ease(x):
    x = max(0.0,min(1.0,x))
    return x*x*(3-2*x)


def font_path():
    configured = os.environ.get('AI_SMA_SAMPLE_FONT')
    if configured and Path(configured).is_file():
        return configured
    candidates = [
        Path(os.environ.get('SYSTEMROOT','C:/Windows'))/'Fonts'/'msyh.ttc',
        Path('/')/'System'/'Library'/'Fonts'/'Supplemental'/'Arial Unicode.ttf',
        Path('/')/'usr'/'share'/'fonts'/'opentype'/'noto'/'NotoSansCJK-Regular.ttc',
    ]
    for value in candidates:
        if value.is_file(): return str(value)
    raise RuntimeError('Set AI_SMA_SAMPLE_FONT to a licensed Chinese-capable font file.')


@functools.lru_cache(maxsize=48)
def font(size):
    return ImageFont.truetype(font_path(),round(size))


def text(draw,xy,words,size=28,fill=INK,anchor=None):
    draw.text(xy,words,font=font(size),fill=fill,anchor=anchor,stroke_width=0)


@functools.lru_cache(maxsize=8)
def background(width,height,dark=False):
    image = Image.new('RGB',(width,height),INK if dark else PAPER)
    d=ImageDraw.Draw(image)
    rng=np.random.default_rng(71)
    color='#26322B' if dark else '#E2DCCF'
    for _ in range(width*height//600):
        x,y=int(rng.integers(width)),int(rng.integers(height))
        d.line((x,y,x+int(rng.integers(1,6)),y),fill=color,width=1)
    return image


def caption(image,words,top=None):
    d=ImageDraw.Draw(image)
    w,h=image.size
    size=30 if w>1000 else 29
    line=words
    bbox=d.textbbox((0,0),line,font=font(size))
    while bbox[2]>w-130:
        size-=1; bbox=d.textbbox((0,0),line,font=font(size))
    x=(w-bbox[2])/2
    y=top if top is not None else h-76
    d.rounded_rectangle((x-24,y-10,x+bbox[2]+24,y+size+15),radius=7,fill=INK)
    text(d,(w/2,y+size/2),line,size,PAPER,'mm')


def signature(image,label,dark=False):
    d=ImageDraw.Draw(image)
    text(d,(40,30),label,16,'#9B9E87' if dark else GREEN)


def arrow(d,a,b,fill=GOLD,width=4):
    d.line((*a,*b),fill=fill,width=width)
    ang=math.atan2(b[1]-a[1],b[0]-a[0])
    pts=[b,(b[0]-16*math.cos(ang-.38),b[1]-16*math.sin(ang-.38)),(b[0]-16*math.cos(ang+.38),b[1]-16*math.sin(ang+.38))]
    d.polygon(pts,fill=fill)


@functools.lru_cache(maxsize=512)
def sphere(size,phase,earth=False):
    # Orthographic visible hemisphere; light vector obeys the stated phase.
    yy,xx=np.mgrid[-1:1:complex(size),-1:1:complex(size)]
    mask=xx*xx+yy*yy<=1
    zz=np.sqrt(np.maximum(0,1-xx*xx-yy*yy))
    light=np.maximum(0,xx*math.sin(phase)+zz*math.cos(phase))
    texture=.94+.06*np.sin(xx*24+np.sin(yy*33))*np.cos(yy*31)
    shade=(.14+.86*light)*texture
    base=np.array((118,155,122) if earth else (231,215,175))
    rgb=np.clip(shade[...,None]*base,0,255).astype('uint8')
    rgba=np.concatenate((rgb,(mask*255).astype('uint8')[...,None]),axis=2)
    return Image.fromarray(rgba)


def moon(image,x,y,r,phase,earth=False):
    size=max(8,round(r*2))
    img=sphere(size,round(phase,2),earth)
    image.paste(img,(round(x-r),round(y-r)),img)


def orbit(image,t,angle=None):
    d=ImageDraw.Draw(image)
    cx,cy,rad=790,324,205
    d.ellipse((cx-rad,cy-rad,cx+rad,cy+rad),outline='#B6BC9E',width=2)
    for y in (210,320,430): arrow(d,(90,y),(430,y))
    text(d,(105,145),'太阳光',28,GOLD)
    moon(image,cx,cy,67,-math.pi/2,True)
    a=angle if angle is not None else math.pi+t*.38
    mx,my=cx+rad*math.cos(a),cy+rad*math.sin(a)
    moon(image,mx,my,40,-math.pi/2)
    d=ImageDraw.Draw(image)
    d.line((cx,cy,mx,my),fill=RED,width=3)
    d.ellipse((cx-9,cy-9,cx+9,cy+9),fill=PAPER)
    text(d,(cx,cy+88),'地球',24,INK,'mm')
    text(d,(mx,my-63),'月球',24,INK,'mm')
    text(d,(110,560),'示意：尺寸与距离不按比例',18,GREEN)


def science(t):
    im=background(1280,720).copy(); d=ImageDraw.Draw(im)
    scene=min(11,int(t//5)); u=t%5; p=ease(u/.45)
    if scene==0:
        moon(im,640,320,205,math.pi*(.76-.68*ease(u/4.5)))
        d.line((230,320,350,320),fill=GREEN,width=3)
        text(d,(230,275),'同一轮月亮',26,GREEN)
    elif scene in (1,2):
        for y in (190,280,370,460):
            x=95+(u*90)%130
            arrow(d,(x,y),(x+310,y),GOLD,5)
        moon(im,850 if scene==1 else 720,325,195 if scene==1 else 235,-math.pi/2)
        text(d,(110,110),'借来的光' if scene==1 else '被照亮的一半',38,INK)
        if scene==2:
            d.line((720,85,720,565),fill=RED,width=2)
    elif scene==3:
        orbit(im,u)
    elif scene in (4,5,6,7):
        phases={4:math.pi,5:2.45,6:math.pi/2,7:0}
        labels={4:'新月',5:'蛾眉月',6:'上弦月',7:'满月'}
        # A 300 ms scale pulse introduces a changed viewpoint, then holds.
        r=195+12*ease(u/.3)
        moon(im,795,320,r,phases[scene])
        text(d,(120,190),labels[scene],62,INK)
        text(d,(125,280),'从地球看',23,GREEN)
        for k in range(8):
            moon(im,135+k*44,390,15,math.pi-k*math.pi/4)
        d.line((110,485,420,485),fill=GREEN,width=2)
    elif scene==8:
        orbit(im,u,2.15)
        text(d,(95,98),'月相 ≠ 地球遮挡',37,INK)
    elif scene==9:
        for k in range(8):
            a=-math.pi/2+k*TAU/8
            moon(im,640+290*math.cos(a),300+215*math.sin(a),49,math.pi-k*math.pi/4)
        text(d,(640,285),'29.5',76,INK,'mm');text(d,(640,352),'天左右 · 新月到新月',24,GREEN,'mm')
        a=-math.pi/2+TAU*ease(u/4.6)
        d.ellipse((634+290*math.cos(a),294+215*math.sin(a),646+290*math.cos(a),306+215*math.sin(a)),fill=RED)
    elif scene==10:
        for y in (210,300,390): arrow(d,(80,y),(470,y),GOLD)
        d.polygon([(635,208),(1120,250),(1120,350),(635,392)],fill='#B7B19D')
        moon(im,600,300,90,-math.pi/2,True)
        moon(im,1000,300,58,1.5)
        d.ellipse((942,242,1058,358),fill='#7C4E3D')
        text(d,(90,100),'月食：进入地球影子',38,INK)
        text(d,(90,540),'月食示意，不是日常月相',23,GREEN)
    else:
        d.rounded_rectangle((330,90,950,580),radius=125,fill=INK)
        moon(im,640+40*ease(u/4.5),315,160,1.1)
        d.rectangle((330,530,950,580),fill=GREEN)
        d.line((640,90,640,170),fill=PAPER,width=8)
    signature(im,'月相 / LIGHT & VIEW')
    caption(im,SCIENCE[scene])
    return im


def notebook(im,cx,cy,scale=1,angle=0,opened=0,writing=0):
    tile=Image.new('RGBA',(700,620)); d=ImageDraw.Draw(tile)
    d.rounded_rectangle((185,80,538,565),radius=19,fill=(0,0,0,32))
    if opened>0:
        # Cover and paper share geometry across aspect-ratio versions.
        left=195-160*opened
        d.rounded_rectangle((left,57,530,552),radius=8,fill='#B99B66')
        d.rectangle((left+12,69,512,535),fill='#F6F0DF')
        d.line((270,72,270,535),fill='#B6AB90',width=3)
        for y in range(137,500,43): d.line((294,y,477,y),fill='#D7D3C2',width=1)
        pts=[]
        for k in range(int(180*writing)):
            x=297+k
            y=200+45*math.sin(k/32)+k*.35
            pts.append((x,y))
        if len(pts)>1:d.line(pts,fill=INK,width=4)
        if pts:
            x,y=pts[-1]
            d.polygon([(x,y),(x+60,y-145),(x+76,y-137),(x+8,y+2)],fill=INK)
            d.polygon([(x,y),(x+11,y-26),(x+18,y-21)],fill=GOLD)
    else:
        d.rounded_rectangle((175,54,520,545),radius=14,fill='#F5EBCF')
        for y in range(521,541,4):d.line((187,y,511,y),fill='#B9A98B',width=1)
        d.rounded_rectangle((165,42,515,525),radius=15,fill='#C59B61')
        d.rectangle((176,44,188,522),fill='#967145')
        for y in range(70,500,18):d.line((196,y,485,y),fill='#C29A63',width=1)
        text(d,(224,108),'FIELD',50,INK)
        text(d,(228,170),'/ 01',25,INK)
        d.rectangle((464,43,481,524),fill=RED)
        d.line((214,460,303,460),fill=INK,width=2)
        text(d,(215,475),'STUDY EDITION',13,INK)
    tile=tile.resize((round(700*scale),round(620*scale)),Image.Resampling.BICUBIC)
    tile=tile.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
    im.paste(tile,(round(cx-tile.width/2),round(cy-tile.height/2)),tile)


def advert(t,vertical=False):
    w,h=(720,1280) if vertical else (1280,720)
    im=background(w,h).copy();d=ImageDraw.Draw(im)
    scene=min(4,int(t//3));u=t%3;p=ease(u/.65)
    cx,cy=(360,655) if vertical else (825,365)
    if scene==0:
        notebook(im,cx+170*(1-p),cy,.96 if vertical else 1.0,-13+7*p)
        words=('把灵感','留在纸上')
    elif scene==1:
        notebook(im,cx,cy,1.12 if vertical else 1.14,6,opened=p)
        words=('翻开','新的可能')
    elif scene==2:
        notebook(im,cx,cy,1.12,0,opened=1,writing=ease(u/2.2))
        words=('一条线','开始成形')
    elif scene==3:
        notebook(im,cx,cy,1.06,-9+18*ease(u/2.4))
        words=('合上','随身带走')
    else:
        notebook(im,cx,cy,.94,2)
        words=('FIELD / 01','让想法落笔')
    if vertical:
        text(d,(70,155),words[0],47,INK)
        text(d,(70,228),words[1],42,INK)
        d.line((70,1080,650,1080),fill=INK,width=2)
        text(d,(70,1120),'虚构产品概念 · 原创验证样片',20,GREEN)
    else:
        text(d,(80,243),words[0],49,INK)
        text(d,(80,320),words[1],44,INK)
        d.line((80,443,365,443),fill=INK,width=2)
        text(d,(80,478),'虚构产品概念',19,GREEN)
    signature(im,'FIELD / OBJECT STUDY')
    return im


def ticket(im,cx,cy,scale=1,angle=0,back=False,wrong=False,corner=False):
    tile=Image.new('RGBA',(410,220));d=ImageDraw.Draw(tile)
    color=RED if wrong else '#D7BF87'
    d.polygon([(20,50),(62,20),(385,20),(385,192),(20,192)],fill=color)
    d.rectangle((34,34,373,181),outline='#826B3F',width=2)
    d.polygon([(19,18),(68,18),(19,53)],fill=(0,0,0,0))
    if back:
        text(d,(200,100),'还给她',38,INK,'mm')
    else:
        text(d,(49,61),'南站',31,INK)
        text(d,(237,62),'21:10',35,INK)
        text(d,(50,135),'N · 021 / RETURN',17,INK)
        for x in range(235,350,7): d.line((x,136,x,163),fill=INK,width=3 if x%2 else 1)
    d.line((310,185,322,209,354,204,349,178),fill=RED,width=5)
    if corner:d.polygon([(20,20),(65,20),(20,51)],fill=color)
    tile=tile.resize((round(410*scale),round(220*scale)),Image.Resampling.BICUBIC)
    tile=tile.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC)
    im.paste(tile,(round(cx-tile.width/2),round(cy-tile.height/2)),tile)


def hand(im,cx,cy,side='left',tone=GREEN,reach=1):
    # Only hands/forearms: shaped fingers, seams and watch identify the character.
    tile=Image.new('RGBA',(640,260));d=ImageDraw.Draw(tile)
    d.polygon([(0,55),(310,70),(333,190),(0,220)],fill=tone)
    d.line((0,83,295,95),fill='#9DAD87',width=3)
    d.line((20,199,305,176),fill='#344D3F',width=4)
    d.polygon([(290,74),(330,77),(346,186),(307,192)],fill='#CBBC91')
    d.polygon([(324,79),(439,74),(504,104),(520,132),(483,162),(350,181)],fill='#BA8867')
    d.polygon([(328,83),(437,81),(494,107),(505,126),(476,148),(347,162)],fill='#D4A685')
    for k in range(4):
        y=95+k*19
        d.rounded_rectangle((420-k*3,y,542-k*12,y+17),radius=8,fill='#D4A685',outline='#AD7D5B',width=1)
    d.polygon([(362,142),(390,180),(448,188),(463,175),(427,150)],fill='#D4A685')
    if tone==GREEN:
        d.rectangle((307,81,330,180),fill=INK)
        d.ellipse((291,112,344,164),fill=GOLD)
        d.ellipse((298,119,337,157),fill=INK)
        d.line((318,138,318,125),fill=PAPER,width=2)
    if side=='right':tile=tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    im.paste(tile,(round(cx-(0 if side=='left' else 640)),round(cy-130)),tile)


def rain(d,t,left=0,right=1280):
    for k in range(48):
        x=left+(k*83+int(t*28))%max(1,right-left)
        y=(k*61+t*330)%560
        d.line((x,y,x-10,y+30),fill='#657363',width=2)


def drama(t,episode=1,wrong=False):
    im=background(1280,720,True).copy();d=ImageDraw.Draw(im)
    scene=min(5,int(t//5));u=t%5;p=ease(u/1.2)
    if episode==1:
        d.polygon([(0,510),(1280,410),(1280,720),(0,720)],fill='#76674B')
        d.rectangle((750,70,1170,400),fill='#344D3F');rain(d,t,760,1170)
        d.line((950,70,950,400),fill=INK,width=12)
        if scene==0:
            ticket(im,650+120*(1-p),360,1.35,-7)
            hand(im,-100+150*(1-p),430)
        elif scene==1:
            ticket(im,730,325,1.55,-4)
            hand(im,90,420)
            d.ellipse((407,153,473,219),outline=RED,width=4)
        elif scene==2:
            d.ellipse((430,95,860,525),fill=PAPER)
            for k in range(12):
                a=k*TAU/12
                d.line((645+185*math.sin(a),310-185*math.cos(a),645+201*math.sin(a),310-201*math.cos(a)),fill=INK,width=4)
            d.line((645,310,530,310),fill=INK,width=10)
            d.line((645,310,645,155),fill=INK,width=6)
            a=TAU*u/60;d.line((645,310,645+180*math.sin(a),310-180*math.cos(a)),fill=RED,width=3)
            text(d,(645,415),'21:00',27,INK,'mm')
        elif scene==3:
            ticket(im,750,310,1.65,4,True)
            hand(im,100,405)
        elif scene==4:
            ticket(im,700-310*p,360+180*p,1.25,-10)
            hand(im,90-290*p,445+150*p)
        else:
            d.rectangle((325,60,920,600),fill='#53664D')
            d.polygon([(325,60),(325+430*p,100),(325+430*p,550),(325,600)],fill='#A69162')
            rain(d,t,350,900)
            hand(im,-300+180*ease(u/.8),420)
    else:
        d.rectangle((0,400,1280,720),fill='#726C58')
        d.rectangle((0,352,1280,362),fill='#A7AB91')
        for x in range(0,1280,180):d.rectangle((x,0,x+15,400),fill='#344D3F')
        rain(d,t)
        if scene==0:
            ticket(im,750,295,1.5,-5,wrong=wrong)
            hand(im,80,400)
        elif scene==1:
            d.rounded_rectangle((300,150,1000,445),radius=9,fill=PAPER)
            text(d,(650,225),'南站 · 末班车',47,INK,'mm')
            text(d,(650,335),'21:10',85,INK,'mm')
            d.rectangle((300,430,300+700*p,445),fill=GOLD)
        elif scene==2:
            ticket(im,650,320,1.25,-5)
            hand(im,-10,425)
            hand(im,1600-380*p,360,'right',GOLD)
        elif scene==3:
            ticket(im,690,310,1.7,0)
            # The matching missing corner is a separate prop until it touches.
            x=270+106*p;y=130+27*p
            d.polygon([(x,y),(x+71,y),(x,y+51)],fill='#D7BF87')
            hand(im,1590-250*p,290,'right',GOLD)
        elif scene==4:
            ticket(im,650+200*p,310,1.25,-5+10*p)
            hand(im,-10-160*p,425)
            hand(im,1220,360,'right',GOLD)
        else:
            x=-200+u*250
            d.rectangle((x-500,80,x+500,350),fill='#B3AB86')
            for k in range(5):d.rectangle((x-470+k*205,110,x-320+k*205,270),fill=INK)
            d.rectangle((300,430,1020,475),fill='#AB8C55')
            d.rectangle((340,475,365,590),fill=INK);d.rectangle((950,475,975,590),fill=INK)
            d.polygon([(510,420),(690,405),(701,462),(518,477)],fill=PAPER)
            text(d,(605,439),'谢谢',29,INK,'mm')
    signature(im,f'遗失的车票 / {episode:02d}',True)
    caption(im,(DRAMA1 if episode==1 else DRAMA2)[scene])
    return im


def music_visual(t):
    im=background(1280,720,True).copy();d=ImageDraw.Draw(im)
    beat=t/.625;phase=beat%1;pulse=math.exp(-phase*6);section=min(3,int(t/7.5))
    cx,cy=640,355
    if section==0:
        # The motif begins as one struck ring; off-beat circles answer it.
        r=170+48*pulse
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=GOLD,width=19)
        a=t*.55
        x=cx+240*math.cos(a);y=cy+240*math.sin(a)
        d.ellipse((x-36,y-36,x+36,y+36),fill=RED)
        d.line((cx,cy,x,y),fill=PAPER,width=3)
        for k in range(6):
            off=(beat*.5+k)%6
            x=100+k*205
            d.line((x,570,x,570-80*max(0,1-off)),fill=GREEN,width=8)
    elif section==1:
        for k in range(6):
            r=60+k*39+pulse*(20-k)
            start=t*45+k*25
            d.arc((cx-r,cy-r,cx+r,cy+r),start,start+245,fill=(GOLD,PAPER,GREEN,RED)[k%4],width=13)
        for k in range(3):
            a=t*.8+k*TAU/3
            x=cx+270*math.cos(a);y=cy+270*math.sin(a)
            d.ellipse((x-20,y-20,x+20,y+20),fill=PAPER)
    elif section==2:
        for row in range(5):
            for col in range(9):
                x=155+col*120;y=135+row*110
                a=t*1.5+(row+col)*.5
                length=28+26*pulse
                d.line((x-length*math.cos(a),y-length*math.sin(a),x+length*math.cos(a),y+length*math.sin(a)),fill=(GOLD,PAPER,RED,GREEN)[(row+col)%4],width=14)
        d.ellipse((cx-65-pulse*20,cy-65-pulse*20,cx+65+pulse*20,cy+65+pulse*20),fill=INK,outline=RED,width=9)
    else:
        settle=ease((t-22.5)/7.5)
        for k in range(12):
            a=k*TAU/12+t*.25*(1-settle)
            r=260*(1-settle)+90
            x=cx+r*math.cos(a);y=cy+r*.62*math.sin(a)
            d.line((cx,cy,x,y),fill=GREEN,width=3)
            rr=16+14*pulse*(1-settle)
            d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(GOLD,PAPER,RED)[k%3])
        rr=45+60*settle
        d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),outline=GOLD,width=15)
    text(d,(55,46),'折光',32,PAPER)
    text(d,(55,620),'REFRACTED / ORIGINAL SYNTH STUDY',16,'#A8AF96')
    return im


def frame(film,t,wrong=False):
    if film=='science': return science(t)
    if film.startswith('ad'):return advert(t,film.endswith('vertical'))
    if film.startswith('drama'):return drama(t,int(film[-1]),wrong)
    return music_visual(t)


def save_wav(path,array):
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as f:
        f.setnchannels(2);f.setsampwidth(2);f.setframerate(RATE)
        f.writeframes((np.clip(array,-.98,.98)*32767).astype('<i2').tobytes())


def score(duration,kind):
    n=round(duration*RATE);audio=np.zeros((n,2),dtype=np.float32)
    rng=np.random.default_rng(919)
    def add(start,sound,level=1,pan=0):
        i=round(start*RATE)
        if i>=n:return
        sound=sound[:n-i]*level
        audio[i:i+len(sound),0]+=sound*(1-pan*.4)
        audio[i:i+len(sound),1]+=sound*(1+pan*.4)
    def note(freq,length,bright=False):
        z=np.arange(round(length*RATE))/RATE
        env=(1-np.exp(-z*150))*np.exp(-z/(.32 if bright else 1.6))
        return (np.sin(TAU*freq*z)+.27*np.sin(TAU*freq*2*z)+.1*np.sin(TAU*freq*3*z))*env
    bpm=96 if kind=='mv' else (112 if kind=='ad' else 74)
    step=60/bpm
    roots=[174.614,146.832,116.541,130.813]
    for beat in range(math.ceil(duration/step)):
        at=beat*step;root=roots[(beat//12)%4]
        section=int(at/7.5) if kind=='mv' else 0
        if beat%2==0:add(at,note(root/2,1.7),.075)
        melody=[1,1.25,1.5,2,1.5,1.25][beat%6]
        add(at,note(root*melody,1.4,True),.065 if kind!='drama' else .018,math.sin(beat)*.6)
        if kind in ('mv','ad'):
            z=np.arange(round(.18*RATE))/RATE
            if beat%2==0:
                kick=np.sin(TAU*(53*z+4*(1-np.exp(-z*25))))*np.exp(-z*24)
                add(at,kick,.17 if section<3 else .1)
            if kind=='ad' or section in (1,2):
                noise=rng.standard_normal(len(z))*np.exp(-z*80)
                add(at+.5*step,noise,.035)
        if kind=='mv' and section==2:
            add(at+.5*step,note(root*2.5,.6,True),.04,.8 if beat%2 else -.8)
    if kind=='drama':
        noise=rng.standard_normal(n).astype(np.float32)
        # Gentle rain with no third-party recordings.
        noise=np.convolve(noise,np.ones(6)/6,mode='same')*.009
        audio+=noise[:,None]
        for at in (1.0,7.1,18.3,24.2):
            z=np.arange(round(.13*RATE))/RATE
            paper=rng.standard_normal(len(z))*np.exp(-z*34)
            add(at,paper,.035)
    fade=min(RATE,n//2)
    audio[:fade]*=np.linspace(0,1,fade)[:,None]
    audio[-fade:]*=np.linspace(1,0,fade)[:,None]
    return audio


def voice_track(film,source_dir,allow_system):
    out=np.zeros((round(DURATIONS[film]*RATE),2),dtype=np.float32)
    cues=[]
    for idx,words in enumerate(SCRIPT[film]):
        supplied=source_dir/f'{film}-{idx:02d}.wav' if source_dir else None
        speech=OUT/'audio'/f'{film}-{idx:02d}.wav'
        if supplied:
            if not supplied.is_file():raise FileNotFoundError(supplied)
            speech=supplied
        elif not speech.exists():
            if not allow_system or platform.system()!='Darwin':
                raise RuntimeError('Narration needs --voice-dir with licensed WAVs or explicit --allow-system-voice on macOS for private tests.')
            speech.parent.mkdir(parents=True,exist_ok=True)
            temp=speech.with_suffix('.aiff')
            run(['say','-v','Tingting','-r','235','-o',str(temp),words])
            run(['ffmpeg','-v','error','-y','-i',str(temp),'-ar',str(RATE),'-ac','1',str(speech)])
            temp.unlink()
        duration=float(probe(speech)['format']['duration'])
        # Ensure the narration ends before the next shot; never accelerate >25%.
        tempo=max(1.0,duration/4.45)
        if tempo>1.25:raise RuntimeError(f'Voice line too long: {film} {idx} ({duration:.2f}s); rewrite or resynthesize.')
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(speech),'-af',f'atempo={tempo},afade=t=in:d=0.012,afade=t=out:st={duration/tempo-.025}:d=0.025','-ar',str(RATE),'-ac','1','-f','f32le','-'])
        clip=np.frombuffer(raw,dtype='<f4').copy()
        peak=float(np.max(np.abs(clip)))
        if peak<.001:raise RuntimeError('Silent speech clip')
        clip*=.50/peak
        start=idx*5+.25;i=round(start*RATE)
        out[i:i+len(clip)]+=clip[:,None]
        cues.append({'start':start,'end':start+len(clip)/RATE,'text':words,'source':speech.name,'source_sha256':sha(speech),'atempo':tempo})
    (OUT/f'{film}.cues.json').write_text(json.dumps(cues,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def stamp(s):
        ms=round(s*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    (OUT/f'{film}.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues))+'\n',encoding='utf-8')
    return out,cues


def render(film,args):
    duration=DURATIONS[film]
    kind='ad' if film.startswith('ad') else ('drama' if film.startswith('drama') else film)
    bed=score(duration,kind)
    cues=[]
    if film in SCRIPT:
        speech,cues=voice_track(film,args.voice_dir,args.allow_system_voice)
        bed*=.24 if film=='science' else .52
        bed+=speech
    audio_path=OUT/f'{film}.wav';save_wav(audio_path,bed)
    w,h=frame(film,0).size
    path=OUT/f'{film}.mp4'
    command=['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{w}x{h}','-framerate',str(FPS),'-i','-','-i',str(audio_path),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-threads','4','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-t',str(duration),str(path)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE)
    start=time.time()
    try:
        for i in range(round(duration*FPS)):
            im=frame(film,i/FPS)
            proc.stdin.write(im.tobytes())
            if i%300==0:print(f'{film}: {i}/{duration*FPS} frames ({time.time()-start:.1f}s)',flush=True)
    except BaseException:
        proc.terminate();raise
    finally:proc.stdin.close()
    if proc.wait()!=0:raise RuntimeError(f'FFmpeg failed: {film}')
    meta=probe(path)
    run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],stdout=subprocess.DEVNULL)
    record={'film':film,'file':path.name,'sha256':sha(path),'duration':float(meta['format']['duration']),'width':w,'height':h,'fps':FPS,'source_sha256':sha(__file__),'speech':bool(cues),'speech_license_scope':'local-private-test-only' if cues and not args.voice_dir else 'original-music-or-user-supplied-speech','review_mode':'self','full_decode':'passed','peak_pcm':float(np.max(np.abs(bed))),'runtime':{'system':platform.system(),'release':platform.release(),'python':sys.version.split()[0]}}
    (OUT/f'{film}.receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)
    return record


def preview():
    rows=[]
    for film in DURATIONS:
        times=[.8,6.5,11.5] if film.startswith('ad') else ([2,12,27,37,47,57] if film=='science' else [2,7,12,17,22,27])
        tiles=[]
        for t in times:
            im=frame(film,t)
            im.thumbnail((426,240))
            tile=Image.new('RGB',(426,273),PAPER);tile.paste(im,((426-im.width)//2,0))
            text(ImageDraw.Draw(tile),(12,244),f'{film} / {t:.1f}s',17,INK)
            tiles.append(tile)
        sheet=Image.new('RGB',(426*3,273*math.ceil(len(tiles)/3)),PAPER)
        for i,tile in enumerate(tiles):sheet.paste(tile,((i%3)*426,(i//3)*273))
        sheet.save(OUT/f'{film}-contact.png')
        rows.append(film)
    print('Previews: '+', '.join(rows))


def continuity_evidence():
    # Frame-level input/output evidence isolates the prop-color repair to episode 2 shot 1.
    evidence={'unit':'episode2/shot01','change':'ticket fill from red to established beige; green cuff, watch, missing corner and red string preserved','upstream':'prop-ticket-v2','unchanged_episode1':sha(OUT/'drama1.mp4') if (OUT/'drama1.mp4').exists() else None,'frames':[]}
    for t in [1,3,7,12,17,22,27]:
        before=frame('drama2',t,wrong=(t<5));after=frame('drama2',t)
        a=hashlib.sha256(before.tobytes()).hexdigest();b=hashlib.sha256(after.tobytes()).hexdigest()
        evidence['frames'].append({'time':t,'before':a,'after':b,'changed':a!=b})
        if t in (1,3):
            sheet=Image.new('RGB',(1280,360));sheet.paste(before.resize((640,360)),(0,0));sheet.paste(after.resize((640,360)),(640,0))
            sheet.save(OUT/f'continuity-repair-{t}.png')
    assert all(x['changed']==(x['time']<5) for x in evidence['frames'])
    (OUT/'continuity-repair.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--all',action='store_true');p.add_argument('--preview',action='store_true')
    p.add_argument('--film',choices=list(DURATIONS));p.add_argument('--voice-dir',type=Path)
    p.add_argument('--allow-system-voice',action='store_true',help='Local private tests only; never distributable or a commercial voice default.')
    args=p.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):p.error('FFmpeg and ffprobe required')
    if args.preview:preview()
    films=list(DURATIONS) if args.all else ([args.film] if args.film else [])
    for film in films:render(film,args)
    if films:continuity_evidence()
    if not films and not args.preview:p.print_help()


if __name__=='__main__':main()
