import type { ReactNode } from 'react'
export type IconName =
  | 'back'
  | 'chevron'
  | 'search'
  | 'message'
  | 'photo'
  | 'link'
  | 'bell'
  | 'settings'
  | 'home'
  | 'check'
  | 'close'
  | 'share'
  | 'safe'
  | 'ban'
  | 'warning'
  | 'uncertain'
  | 'institution'
  | 'people'
export function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    share: (
      <>
        <circle cx="5" cy="12" r="3" />
        <circle cx="19" cy="4" r="3" />
        <circle cx="19" cy="20" r="3" />
        <path d="m8 10 8-5M8 14l8 5" />
      </>
    ),
    safe: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    ban: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m6 6 12 12" />
      </>
    ),
    warning: (
      <>
        <path d="M10 4a2.3 2.3 0 0 1 4 0l7 13a2.3 2.3 0 0 1-2 3H5a2.3 2.3 0 0 1-2-3Z" />
        <path d="M12 8v5m0 3h.01" />
      </>
    ),
    uncertain: (
      <>
        <path d="M12 2c-3 2-6 3-9 4v6c0 5 5 9 9 11 4-2 9-6 9-11V6c-3-1-6-2-9-4Z" />
        <path d="M9.5 9a2.5 2.5 0 1 1 4 2L12 13v1m0 3h.01" />
      </>
    ),
    institution: (
      <>
        <path d="m2 8 10-6 10 6v3H2ZM4 11v9m5-9v9m6-9v9m5-9v9M2 22h20M2 20h20" />
        <circle cx="12" cy="7" r=".5" />
      </>
    ),
    people: (
      <>
        <circle cx="10" cy="7" r="4" />
        <path d="M16 3a4 4 0 0 1 0 8M2 22v-3a7 7 0 0 1 14 0v3Zm15-8a6 6 0 0 1 5 6v2h-3" />
      </>
    ),
    back: <path d="m15 4-8 8 8 8" />,
    chevron: <path d="m9 4 8 8-8 8" />,
    search: (
      <>
        <circle cx="10" cy="10" r="7" />
        <path d="m15 15 7 7" />
      </>
    ),
    message: (
      <>
        <path d="M21 11a9 9 0 0 1-13 8L3 21l1-6A9 9 0 1 1 21 11Z" />
        <path d="M7 11h.1m4 0h.1m4 0h.1" />
      </>
    ),
    photo: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="3" />
        <circle cx="8" cy="8" r="1" />
        <path d="m3 17 6-6 4 4 4-6 4 5" />
      </>
    ),
    link: (
      <>
        <path d="m10 14 4-4m-5 7-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0-1 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" />
      </>
    ),
    bell: <path d="M5 10a7 7 0 0 1 14 0v5l2 3H3l2-3Zm4 8a3 3 0 0 0 6 0" />,
    settings: (
      <>
        <path d="m9 2 6 0 1 3 3 1 3 4-2 3 0 3-4 4-3-1-3 2-4-3v-3l-3-2 1-5 3-1Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    home: (
      <>
        <path d="m2 11 10-9 10 9M5 9v13h14V9M10 22v-8h4v8" />
      </>
    ),
    check: <path d="m5 12 5 5L20 6" />,
    close: <path d="m5 5 14 14M5 19 19 5" />,
  }
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}
