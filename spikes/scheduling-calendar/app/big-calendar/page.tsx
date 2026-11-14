"use client";
import dynamic from "next/dynamic";
const Cal = dynamic(() => import("../../components/RBC"), { ssr: false, loading: () => <p>Loading calendar...</p> });
export default function Page() { return <main><h1>react-big-calendar (fake data)</h1><Cal /></main>; }
