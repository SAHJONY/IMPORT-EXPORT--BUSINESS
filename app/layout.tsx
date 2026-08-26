import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SAHJONY LLC · Global Trade OS',
  description: 'Global import-export operating system',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
