const {test,expect}=require('./offline-fixture');

async function openOwner(page) {
  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await page.evaluate(()=>{
    _authUser={id:'synthetic-media-owner',username:'marked-media-test'};
    _authVerifiedOwnerId=_authUser.id;_authToken='synthetic-local-token';
    resetScreenshot();authUpdateNav();showPage('upload');
  });
}

test('restored screenshot keeps prose and visual description out of topic tags',async({page})=>{
  await openOwner(page);
  const result=await page.evaluate(()=>{
    const body='合成商品说明，白碗放在木桌上。\n【配图视觉描述】奶白汤色。';
    const img={dataURL:'11111111-1111-4111-8111-111111111111',recovered:true};
    _ssImages=[img];_ssOcrCache.set(img.dataURL,{type:'A',title:'合成截图',body,tags:[]});
    _mergeAndShowOcrResults();
    return {plain:_screenshotExtracted,mixed:_splitSsBodyAndTags('正文保留 #美食[话题]# #探店',['美食','合成标签'])};
  });
  expect(result.plain.body).toBe('合成商品说明，白碗放在木桌上。\n【配图视觉描述】奶白汤色。');
  expect(result.plain.tags).toBe('');
  await expect(page.locator('#ss-tags-display')).toHaveText('（未识别到话题）');
  expect(result.mixed).toEqual({body:'正文保留',tags:'#美食 #探店 #合成标签'});
});

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
      if (String(url).endsWith('/billing/plan')) return new Response(JSON.stringify({total_available_credits:10.5}));
      __mediaCalls.push(options.method||'GET');
      const key=new Headers(options.headers).get('X-Request-ID');
      return new Response(JSON.stringify({tasks:[{status:'completed',result_available:true,result:{type:'B',body:'合成画面',cover_desc:'合成画面',ocr_request_id:key}}]}));
    };
    offerMediaRecovery();
  });
  await page.getByRole('button',{name:'读取原素材结果（不重复识别）',exact:true}).click();
  await expect(page.getByRole('button',{name:'继续整理已识别内容',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>__mediaCalls)).toEqual(['GET','GET','GET']);
  await expect(page.locator('#nav-credits-display')).toHaveText('10.5积分');
  await page.evaluate(()=>{chatClearUserState();_authUser={id:'synthetic-other'};_authVerifiedOwnerId=_authUser.id;offerMediaRecovery();});
  expect(await page.locator('[data-media-recovery]').count()).toBe(0);
  expect(await page.evaluate(()=>_ssImages.length)).toBe(0);
});

test('account switch while original image upload completes rejects its result',async({page})=>{
  await openOwner(page);
  const result=await page.evaluate(async()=>{
    let release;const loaded=new Promise(r=>release=r);const tokens=[];
    window.fetch=async(url,options={})=>{
      tokens.push(new Headers(options.headers).get('Authorization'));
      await loaded;return new Response(JSON.stringify({media_ref:'11111111-1111-4111-8111-111111111111'}));
    };
    const pending=privateImageInput('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB').catch(e=>e.message);
    await Promise.resolve();chatClearUserState();_authUser={id:'synthetic-other'};_authVerifiedOwnerId=_authUser.id;_authToken='synthetic-other-token';release();
    return {message:await pending,tokens};
  });
  expect(result.tokens).toEqual(['Bearer synthetic-local-token']);expect(result.message).toContain('账户已切换');
});

test('private image upload preserves bytes under production connect-src without data fetch or duplicate upload',async({page})=>{
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64');
  const uploads=[];
  await page.route('**/synthetic-api/upload-image',async route=>{
    const request=route.request();uploads.push(request);
    expect(request.headers().authorization).toBe('Bearer synthetic-local-token');
    expect(request.postDataBuffer().includes(png)).toBe(true);
    await route.fulfill({json:{media_ref:'11111111-1111-4111-8111-111111111111'}});
  });
  await openOwner(page);
  const result=await page.evaluate(async data=>{
    window.__imageCspViolations=[];
    document.addEventListener('securitypolicyviolation',event=>__imageCspViolations.push(event.blockedURI));
    const policy=document.createElement('meta');policy.httpEquiv='Content-Security-Policy';policy.content="connect-src 'self'";document.head.appendChild(policy);
    return Promise.all([privateImageInput(data),privateImageInput(data)]);
  },'data:image/png;base64,'+png.toString('base64'));
  expect(result).toEqual(['11111111-1111-4111-8111-111111111111','11111111-1111-4111-8111-111111111111']);
  expect(uploads).toHaveLength(1);
  expect(await page.evaluate(()=>__imageCspViolations)).toEqual([]);
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


test('image release leaves both video upload entries closed',async({page})=>{
  await page.addInitScript(()=>{window.NOTEAI_PUBLIC_PRODUCT=true;});
  await openOwner(page);
  await page.evaluate(()=>{
    _publicStatus={image_open:true,video_open:false,media_open:false};
    _authUser.contract_accepted=true;syncProductUI();
  });
  await expect(page.locator('#screenshotInput')).toBeEnabled();
  await expect(page.locator('#genCoverInput')).toBeEnabled();
  await expect(page.locator('#diagVideoInput')).toBeDisabled();
  await expect(page.locator('#genVideoInput')).toBeDisabled();
  expect(await page.locator('#chat-file-input').getAttribute('accept')).toContain('image/png');
  expect(await page.locator('#free-plan-mix').innerText()).toContain('视频暂未开放');
  await page.locator('#chat-file-input').setInputFiles({name:'synthetic-image.png',mimeType:'image/png',
    buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64')});
  await expect.poll(()=>page.evaluate(()=>_chatAttachImage?.name)).toBe('synthetic-image.png');
  const calls=await page.evaluate(async()=>{
    let writes=0;window.fetch=async()=>{writes++;throw Error('unexpected video transport');};
    await _uploadVideoFile(new File(['synthetic'],'unused.mp4',{type:'video/mp4'}));
    await _uploadDiagVideoFile(new File(['synthetic'],'unused.mp4',{type:'video/mp4'}));
    return writes;
  });
  expect(calls).toBe(0);
});


test('all diagnosis entries use the formal industries and late OCR preserves an explicit choice',async({page})=>{
  await openOwner(page);
  const lists=await page.evaluate(()=>['inputDomainSS','inputDomainVideo','inputDomain','genDomain'].map(id=>Array.from(document.getElementById(id).options).map(o=>o.value).filter(Boolean)));
  for(const values of lists) expect(values).toEqual(['美食','旅行','穿搭','美妆','家居','健身','母婴']);
  await page.locator('.input-type', {hasText:'截图上传'}).click();
  await page.evaluate(()=>{_applyScreenshotDomain('运动');document.getElementById('screenshot-result').style.display='block';});
  await expect(page.locator('#inputDomainSS')).toHaveValue('');
  await page.selectOption('#inputDomainSS','健身');
  await page.evaluate(()=>_applyScreenshotDomain('美食'));
  await expect(page.locator('#inputDomainSS')).toHaveValue('健身');
  await page.evaluate(()=>{resetScreenshot();_applyScreenshotDomain('美妆');});
  await expect(page.locator('#inputDomainSS')).toHaveValue('美妆');
});

test('balance shows fractional and zero values even when usage report fails, unknown never becomes zero',async({page})=>{
  await openOwner(page);
  await page.evaluate(async()=>{
    _authVerifiedOwnerId=null; // Existing authenticated password-login path.
    window.fetch=async url=>String(url).endsWith('/billing/plan') ? new Response(JSON.stringify({total_available_credits:8.5})) : new Response('{}',{status:503});
    await loadBillingPlan();
  });
  await expect(page.locator('#nav-credits-display')).toHaveText('8.5积分');
  await page.evaluate(async()=>{window.fetch=async()=>new Response(JSON.stringify({total_available_credits:0}));await refreshCreditBalance();});
  await expect(page.locator('#nav-credits-display')).toHaveText('0积分');
  await expect(page.locator('#nav-credits-display')).toBeVisible();
  await page.evaluate(async()=>{window.fetch=async()=>new Response(JSON.stringify({tasks:[]}));await refreshCreditBalance();});
  await expect(page.locator('#nav-credits-display')).toHaveText('积分待更新');
});

test('late balance responses cannot overwrite a later ledger read or another account',async({page})=>{
  await openOwner(page);
  const result=await page.evaluate(async()=>{
    let release;window.fetch=()=>new Promise(resolve=>release=()=>resolve(new Response(JSON.stringify({total_available_credits:99}))));
    const old=refreshCreditBalance();
    window.fetch=async()=>new Response(JSON.stringify({total_available_credits:6.5}));await refreshCreditBalance();
    release();await old;const newer=document.getElementById('nav-credits-display').textContent;
    window.fetch=()=>new Promise(resolve=>release=()=>resolve(new Response(JSON.stringify({total_available_credits:88}))));
    const pending=refreshCreditBalance();chatClearUserState();const cleared=document.getElementById('nav-credits-display').textContent;
    _authUser={id:'synthetic-other'};_authVerifiedOwnerId=_authUser.id;_authToken='synthetic-other-token';
    window.fetch=async()=>new Response(JSON.stringify({total_available_credits:3}));await refreshCreditBalance();
    release();await pending;return {newer,cleared,current:document.getElementById('nav-credits-display').textContent};
  });
  expect(result).toEqual({newer:'6.5积分',cleared:'',current:'3积分'});
});
