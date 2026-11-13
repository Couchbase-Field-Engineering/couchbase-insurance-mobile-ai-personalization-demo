import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { DataProvider } from '@/src/data/DataContext';
import { AuthProvider } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { DeviceFrame } from '@/src/ui/DeviceFrame';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <DataProvider>
          <DeviceFrame>
            <StatusBar style="light" />
            <Stack
              screenOptions={{
                headerStyle: { backgroundColor: theme.color.ink },
                headerTintColor: theme.color.onDark,
                headerTitleStyle: { fontWeight: '600' },
                contentStyle: { backgroundColor: theme.color.bg },
              }}
            >
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="login" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="cards" options={{ title: 'ID cards & documents', presentation: 'modal' }} />
              <Stack.Screen name="claim" options={{ title: 'Claims', presentation: 'modal' }} />
              <Stack.Screen name="roadside" options={{ title: 'Roadside & emergency', presentation: 'modal' }} />
              <Stack.Screen name="pay" options={{ title: 'Payments & renewals', presentation: 'modal' }} />
              <Stack.Screen name="drive" options={{ title: 'DriveWell', presentation: 'modal' }} />
              <Stack.Screen name="support" options={{ title: 'Support', presentation: 'modal' }} />
              <Stack.Screen name="wellness" options={{ title: 'Health & wellness', presentation: 'modal' }} />
              <Stack.Screen name="coverage" options={{ title: 'On-demand cover', presentation: 'modal' }} />
              <Stack.Screen name="confirm" options={{ title: 'Review & confirm', presentation: 'modal' }} />
            </Stack>
          </DeviceFrame>
        </DataProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
