const { test, expect } = require('@playwright/test');


test('user and Admin pages load pinned scripts without an external CDN', async ({ page }) => {
  const externalScripts = [];
  page.on('request', request => {
    if (
      request.resourceType() === 'script'
      && new URL(request.url()).origin !== 'http://127.0.0.1:5173'
    ) {
      externalScripts.push(request.url());
    }
  });

  await page.goto('/NoteAI_Pro_Demo_Framer.html');
  await expect.poll(() => page.evaluate(() => typeof echarts)).toBe('object');
  await expect.poll(() => page.evaluate(() => typeof lucide)).toBe('object');

  await page.goto('/model/admin.html');
  await expect.poll(() => page.evaluate(() => typeof echarts)).toBe('object');
  expect(externalScripts).toEqual([]);
});
