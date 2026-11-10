import { expect, test } from '@playwright/test'

// UI-only fake risk levels; the live rules do not return normal.
for (const [level, label] of [
  ['dangerous', '위험'], ['suspicious', '의심'],
  ['normal', '정상'], ['insufficient_information', '정보 부족'],
]) {
  test(`가짜 ${label} 응답: 시안 배너·카드·버튼 및 상세 근거`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.route('**/api/v1/analyses', async route => {
      const response = await route.fetch()
      const body = await response.json()
      body.risk_level = level
      if (level === 'normal') { body.risk_factors = []; body.evidence = [] }
      await route.fulfill({ response, json: body })
    })
    await page.goto('/#text')
    await page.getByRole('textbox').fill('은행 담당자입니다. 인증번호를 알려주세요. https://example.invalid/ 에 접속하세요.')
    await page.getByRole('button', { name: '분석하기', exact: true }).click()
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible()
    // 등급 옆에 작은 접미사를 표시한다. 정보 부족은 위험 단계가 아니므로 제외한다.
    await expect(page.locator('.result-banner h2')).toHaveText(level === 'insufficient_information' ? label : `${label}단계`)
    // v3.2: 정보 부족은 순서가 있는 위험 단계로 표시하지 않는다.
    if (level === 'insufficient_information') {
      await expect(page.locator('.risk-scale')).toHaveCount(0)
    } else {
      await expect(page.locator('.risk-scale-step')).toHaveCount(3)
      await expect(page.locator('.risk-scale-step.is-current')).toHaveText(label)
      await expect(page.locator('.risk-scale-step.is-filled')).toHaveCount(
        ['normal', 'suspicious', 'dangerous'].indexOf(level) + 1,
      )
    }
    await expect(page.locator('.result-buttons button')).toHaveCount(2)
    await expect(page.getByRole('button', { name: '가족에게 공유' })).toBeVisible()
    await expect(page.getByRole('button', { name: '홈으로', exact: true })).toBeVisible()
    await expect(page.locator('.result-details')).not.toHaveAttribute('open', '')
    await expect(page.getByText('공식 사이트와 다른 주소가 발견됐어요.', { exact: true })).toHaveCount(0)
    if (level === 'normal') await expect(page.getByText('뚜렷한 위험 신호가 없어요.', { exact: true })).toBeVisible()
    // Uploaded SVG assets must load successfully, including the empty-state icon.
    const images = page.locator('.result-card img')
    for (const icon of await images.all()) {
      await expect(icon).toHaveAttribute('src', /\.svg$/)
      await expect.poll(() => icon.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true)
    }
    for (const icon of await page.locator('.factor-symbol img').all()) {
      await expect(icon).toHaveCSS('filter', 'none')
    }
    await page.screenshot({ path: `test-results/result-${level}.png`, fullPage: true })
    const listen = page.getByRole('button', { name: '음성안내 듣기', exact: true })
    await expect(listen).toHaveAttribute('aria-pressed', 'false')
    await page.screenshot({ path: `test-results/voice-${level}-before.png`, fullPage: true })
    await listen.click()
    const stop = page.getByRole('button', { name: '음성안내 멈춤', exact: true })
    await expect(stop).toHaveAttribute('aria-pressed', 'true')
    expect(await page.locator('.voice-disc').evaluate(el => getComputedStyle(el, '::before').animationName)).toBe('voice-pulse')
    // Freeze a visible animation frame for a reproducible UI preview.
    await page.locator('.voice-disc').evaluate(el => {
      for (const animation of el.getAnimations({ subtree: true })) {
        animation.pause()
        animation.currentTime = 450
      }
    })
    await page.screenshot({ path: `test-results/voice-${level}-playing.png`, fullPage: true })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    expect(await page.locator('.voice-disc').evaluate(el => getComputedStyle(el, '::before').animationName)).toBe('none')
    await stop.click()
    await expect(listen).toBeVisible()
    await expect(page.getByRole('status')).toHaveCount(0)
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.setViewportSize({ width: 320, height: 740 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    // 좁은 화면과 큰 글씨 모드에서도 판정과 설명이 배너 밖으로 나오지 않는다.
    await page.locator('.app-shell').evaluate(el => el.classList.add('large-text'))
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const banner = page.locator('.result-banner')
    expect(await banner.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    await expect(page.locator('.result-status-copy')).toHaveCSS('text-align', 'left')
    await expect(page.locator('.result-banner p span')).toHaveCount(2)
    await page.screenshot({ path: `test-results/result-${level}-large.png`, fullPage: true })
    await page.locator('.result-details > summary').click()
    await expect(page.getByRole('region', { name: 'URL 형식 및 평판' })).toContainText('평판 조회 미연결')
    if (level !== 'normal') await expect(page.locator('q').filter({ hasText: '인증번호를 알려주세요' })).toBeVisible()
  })
}
