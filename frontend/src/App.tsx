import { useState } from 'react';
import DarkHUD from './components/DarkHUD';
import DashboardLayout from './components/DashboardTheme';
import HomePage from './pages/HomePage';
import SoccerPage from './pages/SoccerPage';
import NBAPage from './pages/NBAPage';
import MatchAnalysisPage from './pages/MatchAnalysisPage';
import ResultsPage from './pages/ResultsPage';

type View = 'landing' | 'dashboard';

export type DashPage = 'Home' | 'Soccer' | 'NBA' | 'Match Analysis' | 'Results';

function PageContent({ page }: { page: DashPage }) {
  switch (page) {
    case 'Home':
      return <HomePage />;
    case 'Soccer':
      return <SoccerPage />;
    case 'NBA':
      return <NBAPage />;
    case 'Match Analysis':
      return <MatchAnalysisPage />;
    case 'Results':
      return <ResultsPage />;
  }
}

export default function App() {
  const [view, setView] = useState<View>('landing');
  const [page, setPage] = useState<DashPage>('Home');

  if (view === 'landing') {
    return (
      <button
        type="button"
        onClick={() => setView('dashboard')}
        className="block w-full cursor-pointer text-left"
        aria-label="Open ScorPred app"
      >
        <DarkHUD />
      </button>
    );
  }

  return (
    <DashboardLayout activeItem={page} onNavigate={(item) => setPage(item as DashPage)}>
      <PageContent page={page} />
    </DashboardLayout>
  );
}
