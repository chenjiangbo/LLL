import type {Metadata} from 'next';
import { Literata, Nunito_Sans } from 'next/font/google';
import './globals.css';

const literata = Literata({
  subsets: ['latin'],
  variable: '--font-literata',
});

const nunito = Nunito_Sans({
  subsets: ['latin'],
  variable: '--font-nunito',
});

export const metadata: Metadata = {
  title: 'Terra Analysis',
  description: 'Financial Engine',
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en">
      <body className={`${literata.variable} ${nunito.variable} antialiased font-[family-name:var(--font-nunito)] selection:bg-[#4285f4]/20 selection:text-[#002110]`} suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
