"use client"

import { useEffect, useState } from "react"

export function ViewportWarning() {
  const [isSmallViewport, setIsSmallViewport] = useState(false)

  useEffect(() => {
    const checkViewport = () => {
      setIsSmallViewport(window.innerWidth < 1280)
    }

    checkViewport()
    window.addEventListener("resize", checkViewport)

    return () => window.removeEventListener("resize", checkViewport)
  }, [])

  if (!isSmallViewport) return null

  return (
    <div className="fixed inset-0 bg-background z-50 flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <h1 className="text-2xl font-semibold mb-4">Viewport zu klein</h1>
        <p className="text-muted-foreground mb-2">
          InstantPaper ist für größere Bildschirme optimiert und bietet die beste Erfahrung bei einer Breite von
          mindestens 1280px.
        </p>
        <p className="text-sm text-muted-foreground">
          Bitte vergrößere dein Browserfenster oder nutze ein Gerät mit größerem Bildschirm.
        </p>
      </div>
    </div>
  )
}
