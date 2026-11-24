import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const record = { spoken: [] as string[], cancelled: 0 }
    Object.assign(window, { voiceTest: record })
    Object.defineProperty(SpeechSynthesisUtterance.prototype, 'voice', { configurable: true, writable: true, value: null })
    Object.defineProperties(speechSynthesis, {
      getVoices: { configurable: true, value: () => [{ lang: 'ko-KR', name: 'Test Korean', localService: true }] },
      speak: { configurable: true, value: (item: SpeechSynthesisUtterance) => {
        record.spoken.push(item.text)
        item.onstart?.(new SpeechSynthesisEvent('start', { utterance: item }))
      } },
      cancel: { configurable: true, value: () => { record.cancelled++ } },
      pause: { configurable: true, value: () => {} },
      resume: { configurable: true, value: () => {} },
    })
  })
})

for (const target of ['home', 'edit', 'back'] as const) {
  test(`음성 시작·재개 후 ${target} 이동 시 취소하고 다시 분석해도 자동 재생하지 않는다`, async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '문자 확인하기', exact: true }).click()
    await page.getByRole('textbox', { name: '문자 내용' }).fill('은행입니다. 인증번호를 알려주세요.')
    await page.getByRole('button', { name: '분석하기', exact: true }).click()
    const listen = page.getByRole('button', { name: '분석 결과와 대처 방법 듣기', exact: true })
    await expect(listen).toBeVisible()
    const record = () => page.evaluate(() => (window as unknown as { voiceTest: { spoken: string[]; cancelled: number } }).voiceTest)
    expect((await record()).spoken).toHaveLength(0)
    await listen.click()
    await page.getByRole('button', { name: '음성 안내 일시정지', exact: true }).click()
    await page.getByRole('button', { name: '음성 안내 계속 듣기', exact: true }).click()
    expect((await record()).spoken).toHaveLength(1)
    if (target === 'home') await page.getByRole('button', { name: '홈으로', exact: true }).click()
    else if (target === 'edit') await page.getByRole('button', { name: '다시 확인하기', exact: true }).click()
    else await page.goBack()
    await expect(listen).toHaveCount(0)
    expect((await record()).cancelled).toBe(1)
    if (target !== 'edit') await page.getByRole('button', { name: '문자 확인하기', exact: true }).click()
    await page.getByRole('textbox', { name: '문자 내용' }).fill('가족입니다. 송금해주세요.')
    await page.getByRole('button', { name: '분석하기', exact: true }).click()
    await expect(listen).toBeVisible()
    expect((await record()).spoken).toHaveLength(1)
  })
}

test('가족 공유로 이동하면 결과 음성을 취소하고 돌아와도 자동 재생하지 않는다', async ({ page }) => {
  await page.goto('/#text')
  await page.getByRole('textbox', { name: '문자 내용' }).fill('은행입니다. 인증번호를 알려주세요.')
  await page.getByRole('button', { name: '분석하기', exact: true }).click()
  await page.getByRole('button', { name: '분석 결과와 대처 방법 듣기', exact: true }).click()
  await page.getByRole('button', { name: '가족에게 공유', exact: true }).click()
  await expect(page.getByRole('heading', { name: '가족에게 공유하기' })).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { voiceTest: { cancelled: number } }).voiceTest.cancelled)).toBe(1)
  await page.getByRole('button', { name: '분석 결과로 돌아가기' }).click()
  await expect(page.getByRole('button', { name: '분석 결과와 대처 방법 듣기', exact: true })).toBeVisible()
})
