import {chromium} from 'playwright-core';
import {existsSync,mkdirSync} from 'node:fs';
mkdirSync('screenshots',{recursive:true});
const chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser=await chromium.launch({headless:true,...(existsSync(chrome)?{executablePath:chrome}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
for(const route of ['concepts','atlas','kontur','rost']){
 await page.goto('http://127.0.0.1:5173/'+route);await page.evaluate(()=>document.fonts.ready);
 await page.screenshot({path:'screenshots/'+route+'-desktop.png',fullPage:true});
 if(route!=='concepts'){
  if(await page.locator('input[type=file]').count())throw Error('Guest has own upload input');
  await page.getByRole('button',{name:/Северное поле Неоднородная/}).first().click();
  await page.getByText('ДЕМОНСТРАЦИОННЫЙ ОТЧЁТ',{exact:true}).waitFor();
  await page.locator('video').waitFor();
  const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать демоотчёт',exact:true}).click();await pending;
  await page.getByRole('button',{name:'К примерам',exact:true}).click();
  await page.getByRole('button',{name:/Восточное поле Сравнительно/}).first().click();await page.getByRole('heading',{name:'Сравнительно однородный покров',exact:true}).waitFor();
  await page.getByRole('button',{name:'К примерам',exact:true}).click();
  console.log(route,'PASS guest examples, prepared reports, video, export, no own upload');
 }
 for(const width of [375,768,1024,1440]){await page.setViewportSize({width,height:900});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error('Overflow '+route+' at '+width);if(width===375)await page.screenshot({path:'screenshots/'+route+'-mobile.png',fullPage:true})}
}
if(errors.length)throw Error(errors.join('\n'));console.log('PASS: layouts 375/768/1024/1440, no JavaScript errors');await browser.close();
