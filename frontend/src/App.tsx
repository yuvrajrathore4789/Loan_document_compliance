import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./hooks/AuthContext";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Applications from "./pages/Applications";
import ApplicationDetail from "./pages/ApplicationDetail";
import NewApplication from "./pages/NewApplication";
import VerificationPage from "./pages/VerificationPage";
import Exceptions from "./pages/Exceptions";
import AuditPage from "./pages/AuditPage";
import Rules from "./pages/Rules";

export default function App() {
  const { user } = useAuth();
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="applications" element={<Applications />} />
        <Route path="applications/:id" element={<ApplicationDetail />} />
        <Route path="applications/:id/verification" element={<VerificationPage />} />
        <Route path="upload" element={<NewApplication />} />
        <Route path="exceptions" element={<Exceptions />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="rules" element={<Rules />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
