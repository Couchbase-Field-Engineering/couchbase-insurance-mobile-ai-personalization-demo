import { Platform, type ViewStyle } from 'react-native';

/**
 * Styled after couchbase.com (Nov 2026): black hero sections and white or
 * peach (#FFF0DA) content sections, Couchbase red (#EC1218) for calls to
 * action and links, orange (#FC9D0C) as the second accent, cards with large
 * radii and a soft shadow, bold uppercase eyebrows with wide tracking.
 * The site sets headings in Centra No2 (medium) and body text in Inter;
 * Centra No2 is licensed, so the app uses Inter where it is installed and
 * the platform sans otherwise. The logo is the Couchbase mark and wordmark
 * from the site header (assets/brand).
 */
const shadowCard: ViewStyle = Platform.select({
  ios: { shadowColor: '#000000', shadowOpacity: 0.1, shadowRadius: 16, shadowOffset: { width: 0, height: 4 } },
  android: { elevation: 3 },
  default: { boxShadow: '0 0 32px rgba(0,0,0,0.10)' } as ViewStyle,
}) as ViewStyle;

export const theme = {
  color: {
    ink: '#000000',           // couchbase.com hero / dark sections
    inkSoft: '#1A1A1A',
    red: '#EC1218',           // Couchbase red: buttons, links, the mark
    redActive: '#B30005',
    redDark: '#7C0206',
    redDarkest: '#560003',
    redSoft: '#FFD5D6',
    orange: '#FC9D0C',
    orangeSoft: '#FDCD8C',
    peach: '#FFF0DA',         // couchbase.com warm section background
    peachDark: '#FBCE90',
    cream: '#EAD8BE',
    sand: '#9B9382',
    bg: '#F7F7F7',            // white smoke
    surface: '#FFFFFF',
    text: '#000000',
    body: '#333333',
    muted: '#5C5C5C',
    faint: '#858585',
    border: '#D2D5D9',
    ok: '#0B7A2B',
    okSoft: '#E3F6E8',
    warn: '#A65F00',
    warnSoft: '#FFF0DA',
    danger: '#B30005',
    dangerSoft: '#FFD5D6',
    onDark: '#FFFFFF',
    onDarkMuted: 'rgba(255,255,255,0.72)',
    onDarkFaint: 'rgba(255,255,255,0.14)',
  },
  gradient: {
    hero: ['#000000', '#000000'] as const,
    ink: ['#000000', '#333333'] as const,
    red: ['#EC1218', '#7C0206'] as const,
    ember: ['#FC9D0C', '#EC1218'] as const,
    sand: ['#6E6757', '#9B9382'] as const,
  },
  // Area accents: the eight things the app does.
  area: {
    documents: '#333333',
    claims: '#EC1218',
    roadside: '#B30005',
    billing: '#FC9D0C',
    telematics: '#6E6757',
    support: '#000000',
    wellness: '#0B7A2B',
    coverage: '#7C0206',
  } as Record<string, string>,
  font: {
    display: Platform.select({ ios: 'System', android: 'sans-serif-medium', default: "Inter, -apple-system, 'Segoe UI', Roboto, sans-serif" }) as string,
    body: Platform.select({ ios: 'System', android: 'sans-serif', default: "Inter, -apple-system, 'Segoe UI', Roboto, sans-serif" }) as string,
  },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  type: { xs: 11, sm: 13, md: 15, lg: 17, xl: 20, title: 26, hero: 32 },
  radius: 22,       // cards (the site uses 30px on desktop)
  radiusSm: 12,     // buttons and inputs, as on couchbase.com
  shadow: { card: shadowCard },
} as const;

export type GradientKey = keyof typeof theme.gradient;
