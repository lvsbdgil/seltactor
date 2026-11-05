import type {PDFPage,PDFFont} from 'pdf-lib';
export type PdfReport={title:string;mode:'demo'|'openai';field:string;crop:string;date:string;summary:string;observations:{label:string;description:string;recommendation:string;source?:string;severity?:string}[];limitations:string[];disclaimer:string;model?:string};
export async function buildReportPdf(report:PdfReport,fontBytes:Uint8Array,boldBytes:Uint8Array){
 const [{PDFDocument,rgb},{default:fontkit}]=await Promise.all([import('pdf-lib'),import('@pdf-lib/fontkit')]);
 const ink=rgb(.14,.20,.16),muted=rgb(.34,.39,.34),green=rgb(.17,.29,.20),line=rgb(.83,.87,.81);
 const pdf=await PDFDocument.create();pdf.registerFontkit(fontkit);const regular=await pdf.embedFont(fontBytes,{subset:true}),bold=await pdf.embedFont(boldBytes,{subset:true});
 pdf.setTitle('SELTACTOR - '+report.title);pdf.setAuthor('SELTACTOR');pdf.setSubject(report.mode==='demo'?'Демонстрационный отчёт':'Визуальное обследование посевов');pdf.setLanguage('ru-RU');
 const width=595.28,height=841.89,margin=48,contentWidth=width-margin*2;let page:PDFPage;let y=0;
 const clean=(s:string)=>String(s??'').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g,'').replace(/[\u2011\u2013\u2014]/g,'-').replace(/\t/g,'    ');
 function addPage(){page=pdf.addPage([width,height]);page.drawRectangle({x:0,y:height-84,width,height:84,color:green});page.drawText('SELTACTOR',{x:margin,y:height-43,size:19,font:bold,color:rgb(.91,.95,.86)});page.drawText('МОНИТОРИНГ СОСТОЯНИЯ ПОСЕВОВ',{x:margin,y:height-63,size:8,font:regular,color:rgb(.78,.85,.73)});y=height-113;}
 function ensure(space:number){if(y-space<62)addPage()}
 function wrapped(text:string,font:PDFFont,size:number){const lines:string[]=[];for(const paragraph of clean(text).split('\n')){let row='';for(const word of paragraph.split(/\s+/).filter(Boolean)){if(font.widthOfTextAtSize((row?row+' ':'')+word,size)<=contentWidth){row+=(row?' ':'')+word;continue}if(row){lines.push(row);row=''}let piece='';for(const char of word){if(font.widthOfTextAtSize(piece+char,size)>contentWidth&&piece){lines.push(piece);piece=''}piece+=char}row=piece}lines.push(row)}return lines}
 function text(value:string,size=10,font=regular,color=ink){const leading=size*1.55;for(const row of wrapped(value,font,size)){ensure(leading);if(row)page.drawText(row,{x:margin,y,size,font,color});y-=leading}}
 function space(n=12){y-=n}
 function heading(value:string){ensure(65);space(14);text(value,13,bold,green);space(5)}
 addPage();text(report.mode==='demo'?'ДЕМОНСТРАЦИОННЫЙ ОТЧЁТ':'ОТЧЁТ ПО МАТЕРИАЛАМ ОБСЛЕДОВАНИЯ',9,bold,green);space(10);text(report.title,23,bold);space(12);
 text('Поле: '+report.field,10,bold);text('Культура: '+report.crop);text('Дата съёмки: '+report.date);if(report.model)text('Модель: '+report.model,9,regular,muted);
 heading('Краткий результат');text(report.summary);
 if(report.mode==='demo'){space(12);text('Учебные иллюстрации и заранее подготовленный отчёт. OpenAI не использовался. Этот пример не описывает реальное хозяйство.',9,bold,muted)}
 heading('Наблюдения');
 if(!report.observations.length)text('На просмотренных материалах отдельные наблюдения не выделены. Это не подтверждает отсутствие повреждений на всём поле.');
 report.observations.forEach((o,i)=>{ensure(100);space(8);text(`${i+1}. ${o.label}`,12,bold);if(o.severity){const priorities:Record<string,string>={high:'Приоритетный осмотр',medium:'Обратить внимание',low:'Наблюдение'};text('Приоритет проверки: '+(priorities[o.severity]||o.severity),9,regular,muted)}text(o.description);space(6);text('Следующий шаг',9,bold);text(o.recommendation);if(o.source){space(5);text('Источник: '+o.source,9,regular,muted)}space(10);ensure(10);page.drawLine({start:{x:margin,y},end:{x:width-margin,y},color:line,thickness:.6});space(8)});
 heading('Ограничения');report.limitations.forEach((s,i)=>{text(`${i+1}. ${s}`,9,regular,muted);space(5)});heading('Заключение проверяет агроном');text(report.disclaimer,10,regular,ink);
 const pages=pdf.getPages();pages.forEach((p,i)=>{p.drawLine({start:{x:margin,y:44},end:{x:width-margin,y:44},color:line,thickness:.6});p.drawText('SELTACTOR / '+(report.mode==='demo'?'Демонстрация':'Предварительный визуальный анализ'),{x:margin,y:29,size:8,font:regular,color:muted});p.drawText(`${i+1} / ${pages.length}`,{x:width-margin-35,y:29,size:8,font:regular,color:muted})});
 return pdf.save();
}
export async function downloadReportPdf(report:PdfReport,filename:string){
 const [regular,bold]=await Promise.all(['/fonts/font-0.woff2','/fonts/font-3.woff2'].map(async url=>{const r=await fetch(url);if(!r.ok)throw Error('Не удалось загрузить шрифт отчёта. Повторите скачивание.');return new Uint8Array(await r.arrayBuffer())}));
 const bytes=await buildReportPdf(report,regular,bold);const buffer=new ArrayBuffer(bytes.byteLength);new Uint8Array(buffer).set(bytes);const url=URL.createObjectURL(new Blob([buffer],{type:'application/pdf'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
