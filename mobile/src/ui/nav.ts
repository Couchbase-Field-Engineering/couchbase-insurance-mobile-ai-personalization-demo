import { router } from 'expo-router';
import type { Cta } from '../types';
import type { IconName } from './components';

export const KIND_ICON: Record<string, IconName> = {
  payment: 'wallet',
  renewal: 'refresh-circle',
  claim: 'camera',
  idcard: 'card',
  drive: 'speedometer',
  roadside: 'car-sport',
  telehealth: 'videocam',
  deductible: 'pie-chart',
  vetbill: 'paw',
  wearable: 'watch',
  coverage: 'flash',
};

export const KIND_LABEL: Record<string, string> = {
  payment: 'Payment',
  renewal: 'Renewal',
  claim: 'Your claim',
  idcard: 'ID cards',
  drive: 'DriveWell',
  roadside: 'Roadside',
  telehealth: 'Telehealth',
  deductible: 'Deductible',
  vetbill: 'Pet plan',
  wearable: 'Wellness rewards',
  coverage: 'On-demand cover',
};

export const ACTIVITY_ICON: Record<string, IconName> = {
  document: 'document-text', details: 'person', change: 'create', agent: 'headset', claim: 'camera', evidence: 'images',
  roadside: 'car-sport', sos: 'alert-circle', payment: 'wallet', autopay: 'repeat', renewal: 'refresh-circle', waiver: 'gift',
  telematics: 'speedometer', trip: 'navigate', discount: 'pricetag', telehealth: 'videocam', vetbill: 'paw', wearable: 'watch',
  coverage: 'flash',
};

/**
 * Open what's behind a feed card or a chat suggestion:
 *  - `screen`: a purpose-built screen (cards, claim, roadside, pay, drive, support, wellness, coverage)
 *  - `tool`:   a one-tap action, confirmed on /confirm and queued offline-first
 *  - `ask`:    a question for the Chat tab (queued through `queueAsk`)
 */
export function openAction(a: Cta, opts: { title?: string; price?: string; queueAsk?: (q: string) => void } = {}) {
  if (a.ask) {
    opts.queueAsk?.(a.ask);
    router.navigate('/(tabs)');
    return;
  }
  if (a.screen) {
    router.push({ pathname: `/${a.screen}` as never, params: Object.fromEntries(Object.entries(a.args ?? {}).map(([k, v]) => [k, String(v)])) });
    return;
  }
  if (a.tool) {
    router.push({
      pathname: '/confirm',
      params: { tool: a.tool, args: JSON.stringify(a.args ?? {}), title: opts.title ?? a.label, price: opts.price ?? '' },
    });
  }
}
