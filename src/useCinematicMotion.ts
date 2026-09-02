import {useEffect} from 'react';
import Lenis from 'lenis';
import gsap from 'gsap';
import {ScrollTrigger} from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function useCinematicMotion(key:string){
 useEffect(()=>{
  if(typeof window==='undefined'||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const lenis=new Lenis({duration:1.15,smoothWheel:true,wheelMultiplier:.82,touchMultiplier:1.05});
  let frame=0;
  const tick=(time:number)=>{lenis.raf(time);frame=requestAnimationFrame(tick)};
  frame=requestAnimationFrame(tick);
  lenis.on('scroll',ScrollTrigger.update);
  const ctx=gsap.context(()=>{
   gsap.utils.toArray<HTMLElement>('[data-cinematic]').forEach((section,index)=>{
    const media=section.querySelector<HTMLElement>('[data-cinematic-media]');
    const reveals=section.querySelectorAll<HTMLElement>('[data-cinematic-reveal]');
    if(media)gsap.fromTo(media,{scale:1.08,yPercent:index%2?2:-2},{scale:1,yPercent:index%2?-2:2,ease:'none',scrollTrigger:{trigger:section,start:'top bottom',end:'bottom top',scrub:1.1}});
    if(reveals.length)gsap.fromTo(reveals,{opacity:0,y:44},{opacity:1,y:0,duration:1.1,stagger:.1,ease:'power3.out',scrollTrigger:{trigger:section,start:'top 76%',once:true}});
   });
   gsap.utils.toArray<HTMLElement>('[data-float]').forEach((node,index)=>{
    gsap.to(node,{y:index%2?-9:9,duration:3.6+index*.3,repeat:-1,yoyo:true,ease:'sine.inOut'});
   });
  });
  ScrollTrigger.refresh();
  return()=>{cancelAnimationFrame(frame);lenis.destroy();ctx.revert();ScrollTrigger.getAll().forEach(trigger=>trigger.kill())};
 },[key]);
}
