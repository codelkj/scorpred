import { useState } from 'react';
import DarkHUD from './components/DarkHUD';
import DashboardLayout from './components/DashboardTheme';
import StrategyLabSection from './components/StrategyLabSection';
import HomePage from './pages/HomePage';
import SoccerPage from './pages/SoccerPage';
import NBAPage from './pages/NBAPage';
import MatchAnalysisPage from './pages/MatchAnalysisPage';
import PerformancePage from './pages/PerformancePage';

type View = 'landing' | 'dashboard';

type DashPage =
  | 'Dashboard'
  | 'Soccer'
  | 'NBA'
  | 'Match Analysis'
  | 'Strategy Lab'
  | 'Performance'
  | 'Props Engine'
  | 'Settings';

function PageContent({ page }: { page: DashPage }) {
  switch (page) {
    case 'Dashboard':      return <HomePage />;
    case 'Soccer':         return <SoccerPage />;
    case 'NBA':            return <NBAPage />;
    case 'Match Analysis': return <MatchAnalysisPage />;
    case 'Strategy Lab':   return <StrategyLabSection />;
    case 'Performance':    return <PerformancePage />;
    default:
      return (
        <div className="page-stack">
          <div>
            <p className="page-eyebrow">// Coming Soon</p>
            <h1 className="page-title">{page}</h1>
            <div className="mt-4 h-px bg-gradient-to-r from-[#00ff87]/20 to-transparent" />
          </div>
          <div className="card">
            <p className="text-neutral-500 text-sm font-mono">
              This section is under construction.
            </p>
          </div>
        </div>
      );
  }
}

export default function App() {
  const [view, setView] = useState<View>('landing');
  const [page, setPage] = useState<DashPage>('Dashboard');

  if (view === 'landing') {
    return (
      <div onClick={() => setView('dashboard')} className="cursor-pointer">
        <DarkHUD />
      </div>
    );
  }

  return (
    <DashboardLayout activeItem={page} onNavigate={(item) => setPage(item as DashPage)}>
      <PageContent page={page} />
    </DashboardLayout>
  );
}
