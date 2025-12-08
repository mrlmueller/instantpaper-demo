import { LoginButton } from "@/app/components/auth/LoginButton";

export default function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-2">InstantPaper</h1>
        <p className="text-gray-600 mb-8">Sign in to continue</p>
        <LoginButton />
      </div>
    </div>
  );
}
