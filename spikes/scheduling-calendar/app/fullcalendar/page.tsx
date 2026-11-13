"use client";
import dynamic from "next/dynamic";
const Cal = dynamic(() => import("../../components/FC"), { ssr: false, loading: () => <p>Loading calendar...</p> });
export default function Page() { return <main><h1>FullCalendar 7 (fake data)</h1><Cal /></main>; }
