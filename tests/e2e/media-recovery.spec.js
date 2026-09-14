const {test,expect}=require('./offline-fixture');

async function openOwner(page) {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(()=>{
    _authUser={id:'synthetic-media-owner',username:'marked-media-test'};
    _authVerifiedOwnerId=_authUser.id;_authToken='synthetic-local-token';
    resetScreenshot();showPage('upload');
  });
}

test('media recovery reads original objects and never merges an appended batch on refresh',async({page})=>{
  await openOwner(page);
  await page.evaluate(async()=>{
    const ids=[1,2,3].map(n=>`${n}1111111-1111-4111-8111-111111111111`);
    const rows=ids.map((key,i)=>({key,kind:'extract',mediaRef:`${i+4}1111111-1111-4111-8111-111111111111`}));
    const previous=await ocrMergeRequestKey(ids.slice(0,2).map(id=>({ocr_request_id:id})));
    rows.push({key:previous,kind:'merge'});
    localStorage.setItem(mediaReferenceKey(_authUser.id),JSON.stringify(rows));
    window.__mediaCalls=[];
    window.fetch=async(url,options={})=>{
      __mediaCalls.push(options.method||'GET');
      const key=new Headers(options.headers).get('X-Request-ID');
      return new Response(JSON.stringify({tasks:[{status:'completed',result_available:true,result:{type:'B',body:'合成画面',cover_desc:'合成画面',ocr_request_id:key}}]}));
    };
    offerMediaRecovery();
  });
  await page.getByRole('button',{name:'读取原素材结果（不重复识别）',exact:true}).click();
  await expect(page.getByRole('button',{name:'继续整理已识别内容',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>__mediaCalls)).toEqual(['GET','GET','GET']);
  await page.evaluate(()=>{chatClearUserState();_authUser={id:'synthetic-other'};_authVerifiedOwnerId=_authUser.id;offerMediaRecovery();});
  expect(await page.locator('[data-media-recovery]').count()).toBe(0);
  expect(await page.evaluate(()=>_ssImages.length)).toBe(0);
});

test('account switch while image bytes load prevents upload under the new account',async({page})=>{
  await openOwner(page);
  const result=await page.evaluate(async()=>{
    let release;const loaded=new Promise(r=>release=r);let writes=0;
    window.fetch=async(url,options={})=>{
      if(String(url).startsWith('data:'))return {blob:async()=>{await loaded;return new Blob(['synthetic']);}};
      writes++;return new Response(JSON.stringify({media_ref:'11111111-1111-4111-8111-111111111111'}));
    };
    const pending=privateImageInput('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB').catch(e=>e.message);
    await Promise.resolve();chatClearUserState();_authUser={id:'synthetic-other'};_authVerifiedOwnerId=_authUser.id;_authToken='synthetic-other-token';release();
    return {message:await pending,writes};
  });
  expect(result.writes).toBe(0);expect(result.message).toContain('账户已切换');
});

test('changed screenshot batch is preserved while old result GET is pending',async({page})=>{
  await openOwner(page);
  await page.evaluate(()=>{
    const key='11111111-1111-4111-8111-111111111111';
    localStorage.setItem(mediaReferenceKey(_authUser.id),JSON.stringify([{key,kind:'extract',mediaRef:key}]));
    window.fetch=async()=>{await new Promise(resolve=>window.__releaseMedia=resolve);return new Response(JSON.stringify({tasks:[{status:'completed',result_available:true,result:{type:'B',body:'旧合成画面',cover_desc:'旧合成画面',ocr_request_id:key}}]}));};
    offerMediaRecovery();
  });
  await page.getByRole('button',{name:'读取原素材结果（不重复识别）',exact:true}).click();
  await page.evaluate(()=>{_invalidateSsAggregateState();_ssImages=[{dataURL:'new-synthetic-material'}];__releaseMedia();});
  await expect(page.locator('[data-media-recovery]')).toContainText('当前素材已变化');
  expect(await page.evaluate(()=>_ssImages[0].dataURL)).toBe('new-synthetic-material');
});
