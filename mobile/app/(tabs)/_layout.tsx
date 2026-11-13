import { Ionicons } from '@expo/vector-icons';
import { Redirect, Tabs } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import type { IconName } from '@/src/ui/components';

const ICONS: Record<string, [IconName, IconName]> = {
  index: ['chatbubbles', 'chatbubbles-outline'],
  foryou: ['sparkles', 'sparkles-outline'],
  activity: ['list', 'list-outline'],
  profile: ['person-circle', 'person-circle-outline'],
};

export default function TabsLayout() {
  const { ready, session } = useAuth();
  const insets = useSafeAreaInsets();
  if (ready && !session) return <Redirect href="/login" />;
  return (
    <Tabs
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: theme.color.ink,
        tabBarInactiveTintColor: theme.color.faint,
        tabBarStyle: {
          backgroundColor: theme.color.surface,
          borderTopColor: theme.color.border,
          // Room for icon + label above the home indicator.
          height: 60 + insets.bottom,
          paddingBottom: insets.bottom,
        },
        tabBarItemStyle: { paddingVertical: 4 },
        // Phone layout in every viewport (the web build otherwise puts labels beside icons on wide windows).
        tabBarLabelPosition: 'below-icon',
        tabBarLabelStyle: { fontSize: theme.type.xs, fontWeight: '700', lineHeight: 17 },
        tabBarIcon: ({ focused, color, size }) => (
          <Ionicons name={(ICONS[route.name] ?? ICONS.index)[focused ? 0 : 1]} size={size - 2} color={focused ? theme.color.red : color} />
        ),
      })}
    >
      <Tabs.Screen name="index" options={{ title: 'Chat' }} />
      <Tabs.Screen name="foryou" options={{ title: 'For You' }} />
      <Tabs.Screen name="activity" options={{ title: 'Activity' }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile' }} />
    </Tabs>
  );
}
