import { expect, test } from '@playwright/test'

for (const type of ['text', 'url']) {
  for (const large of [false, true]) {
    test(`${type} ${large ? '큰' : '기본'} 글씨: 줄바꿈 후 지우기 아이콘의 크기·정렬·동작`, async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 740 })
      await page.goto(`/#${type}`)
      if (large) await page.locator('.app-shell').evaluate(el => el.classList.add('large-text'))
      const field = page.getByRole('textbox', { name: type === 'url' ? 'URL 주소' : '문자 내용' })
      await field.fill('linkexample'.repeat(18) + '\n두 번째 줄\n세 번째 줄')
      const clear = page.getByRole('button', { name: '입력 내용 지우기' })
      const icon = clear.locator('svg')
      const buttonBox = (await clear.boundingBox())!
      const iconBox = (await icon.boundingBox())!
      expect(iconBox.width).toBe(16)
      expect(iconBox.height).toBe(16)
      expect(Math.abs(iconBox.x + iconBox.width / 2 - buttonBox.x - buttonBox.width / 2)).toBeLessThan(0.5)
      expect(Math.abs(iconBox.y + iconBox.height / 2 - buttonBox.y - buttonBox.height / 2)).toBeLessThan(0.5)
      const firstLine = await field.evaluate(el => {
        const style = getComputedStyle(el)
        return el.getBoundingClientRect().top + parseFloat(style.paddingTop) + parseFloat(style.lineHeight) / 2
      })
      expect(Math.abs(buttonBox.y + buttonBox.height / 2 - firstLine)).toBeLessThan(1)
      await page.screenshot({ path: `test-results/clear-${type}-${large ? 'large' : 'default'}.png`, fullPage: true })
      await clear.click()
      await expect(field).toHaveValue('')
      await expect(field).toBeFocused()
      await expect(clear).toHaveCount(0)
      await expect(page.locator('#message-count')).toContainText('0 / 10,000자')
    })
  }
}
