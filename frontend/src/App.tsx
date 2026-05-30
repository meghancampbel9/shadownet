import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { SetupPage } from "@/pages/Setup";
import { LoginPage } from "@/pages/Login";
import { RegisterPage } from "@/pages/Register";
import { DashboardPage } from "@/pages/Dashboard";
import { ContactsPage } from "@/pages/Contacts";
import { ContactDetailPage } from "@/pages/ContactDetail";
import { MessagesPage } from "@/pages/Messages";
import { ConnectPage } from "@/pages/Connect";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token, isReady } = useAuth();
  if (!isReady) return null;
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const { isReady } = useAuth();
  if (!isReady) return null;

  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<DashboardPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="contacts/:id" element={<ContactDetailPage />} />
        <Route path="messages" element={<MessagesPage />} />
        <Route path="connect" element={<ConnectPage />} />
      </Route>
    </Routes>
  );
}
