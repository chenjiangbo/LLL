import type {Metadata} from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'LLL 交易研究',
  description: 'A 股交易研究与复盘工具',
  icons: {
    icon: '/icon.svg',
  },
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en">
      <body className="antialiased font-[family-name:var(--font-nunito)] selection:bg-[#4285f4]/20 selection:text-[#002110]" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
