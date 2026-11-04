import {chromium} from 'playwright-core';
import { existsSync, mkdirSync } from 'node:fs';
mkdirSync('screenshots', {recursive:true});
const chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser=await chromium.launch({...(existsSync(chrome)?{executablePath:chrome}:{}),headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
for(const route of ['concepts','atlas','kontur','rost']){
 await page.goto('http://127.0.0.1:5173/'+route);await page.evaluate(()=>document.fonts.ready);
 await page.screenshot({path:'screenshots/'+(route||'concepts')+'-desktop.png',fullPage:true});
 console.log(route||'gallery',await page.title(),await page.locator('body').evaluate(el=>({width:el.scrollWidth,viewport:innerWidth})));
 await page.setViewportSize({width:375,height:850});await page.screenshot({path:'screenshots/'+(route||'concepts')+'-mobile.png',fullPage:true});
 const mobile=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));if(mobile.width>mobile.viewport)throw Error('Overflow '+route+JSON.stringify(mobile));
 await page.setViewportSize({width:1440,height:1050});
 if(route!=='concepts'){
 await page.getByRole('button',{name:route==='rost'?'Продолжить':'Анализировать материалы',exact:true}).click();await page.getByRole('alert').waitFor();
 await page.getByRole('button',{name:route==='rost'?'Попробовать на примере':'Открыть демопример',exact:route!=='rost'}).click();
 await page.getByText('field_12_aerial.jpg',{exact:true}).waitFor();
 await page.getByRole('button',{name:route==='rost'?'Продолжить':'Запустить демоанализ',exact:true}).click();
 if(route==='rost')await page.getByRole('button',{name:'Запустить демоанализ',exact:true}).click();
 await page.getByText('ДЕМОНСТРАЦИОННЫЙ ОТЧЁТ',{exact:true}).waitFor();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать демоотчёт'}).click();const download=await downloadPromise;console.log(route,'report download:',download.suggestedFilename());
 await page.getByRole('button',{name:'Новое обследование',exact:true}).last().click();
 await page.locator('input[type=file]').setInputFiles({name:'real-test.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDrsAAAAASUVORK5CYII=','base64')});
 await page.getByText('real-test.png',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Удалить real-test.png'}).click();
 await page.locator('input[type=file]').setInputFiles({name:'unsupported.txt',mimeType:'text/plain',buffer:Buffer.from('test')});await page.getByRole('alert').waitFor();
 console.log(route,'PASS: empty validation, demo, report, export, upload, remove, type validation');
 }
}
for(const width of [375,768,1024,1440]){for(const route of ['concepts','atlas','kontur','rost']){await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:5173/'+route);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error('Horizontal overflow '+route+' at '+width)}}
console.log('JS errors:',errors);if(errors.length)throw Error(errors.join('\n'));
await browser.close();
