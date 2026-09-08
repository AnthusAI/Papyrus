_Coding agents didn't just get better. Useful coding capability got dramatically cheaper._

That's the change I think we've underestimated. For years, the AI-coding story was about capability: bigger context windows, better tool use, and higher benchmark scores. That story is still true at the frontier. But the more practical story in 2026 is that last year's useful coding capability moved way down the cost curve.

Since Andrej Karpathy coined "vibe coding" in February 2025, the cost of reaching roughly the same benchmark performance has fallen by close to an order of magnitude for software-engineering tasks. At the same time, agents have gotten much better at staying on a task for hours instead of answering one prompt and stopping.

Those aren't two separate trends. They multiply. Cheaper models make long agent loops affordable, and longer agent loops change what you can delegate.

You can see it in everyday work: boilerplate, lint fixes, tests, code explanations, and well-scoped repository issues. A model doesn't need to be the smartest model available to be the right model for those jobs. It needs to clear the quality bar at a sensible cost.

So the useful question isn't, "What's the smartest model?" It's: what does it cost to complete this kind of engineering task at the quality I need?

There was a look you could spot at any tech conference in 2025: an engineer walking through the halls carrying a laptop cracked open at hip level, carefully, like a tray of water glasses. Closing the lid killed the agent loop and killed whatever the agent was working on, so the lid stayed open.

That was a year ago. It feels archaic now.

Through 2024 and into early 2025, coding agents lived inside your IDE or your terminal. They ran on your clock, on your machine, in your process. If the laptop slept, the agent stopped. If you wanted to check on it, you walked back to the desk.

If you used more than one agent product — and by mid-2025 most serious practitioners were running Cursor and Claude Code at minimum, often Codex as well — you were the integration layer. You switched tabs, copied context from one conversation into another, and babysat every session individually. The agents could not see each other's work.

I built Kanbus to solve the part of this problem that was solvable without waiting for vendors. The idea was simple: if every issue is a JSON file inside a Git repository, then any agent that can clone the repo can read the board and write to it. Git is the transport. The repository is the shared memory.

What changed was not one thing. Three trends hit at the same time, and they multiplied. Cheaper tokens made long loops viable. Agents got better at running long. The harnesses shipped real remote orchestration.

I didn't even hear about the bug until after it was fixed.

A Researcher agent found a problem and reported it to a Software Director agent. The director recorded the problem, assigned coding agents to work on separate parts of it in parallel, reviewed what they returned, rejected work that did not meet its requirements, combined the accepted changes, and delivered the result back to the Researcher. The Researcher checked whether the original problem had actually been solved and, when the fix fell short, sent it back around the loop.

I had defined those roles. Early on, I sometimes told one agent to consult another. But I was no longer copying every message, tracking every coding session, or personally moving the work through every handoff. The agents had started collaborating through the responsibilities I gave them.

What surprised me wasn't that an agent could write code. It was watching one piece of software supervise another.

Kanbus gave that work a shared structure. But Kanbus organized the work; it did not manage it. It did not read the code and form an opinion. It did not decide that a test result was inadequate, reject a change because the documentation was missing, or determine which specialist should take the next step.

The answer was not a faster model. It was management. Dispatch alone is a queue. Supervision includes judgment.

I needed a picture of a cute kitten to post on the Internet, since we all have to do our part or else there would be a shortage. I asked ChatGPT to make a picture of a cute kitten. And it made one.

How did this AI model somehow learn to make a picture of a cute kitten? Did the researchers at OpenAI somehow 'upload' the kitten-drawing skill set into GPT-4, like Neo learning Kung Fu in The Matrix by plugging a cable into the back of his head?

Not really. The answer is simpler, and it's a preview of a new type of software solution.

Imagine you're conversing with an airline assistant who can type on their terminal at superhuman speeds to fetch the latest information to answer your questions. This scenario is akin to how it works when we speak with an AI agent that can look up facts or draw pictures. Imagine the agent pausing the conversation to use a tool to look up the latest data or perform a quick calculation.

These tools that the model can use are called "actions" in general for AI agents. Actions are computer programs that you give to the agent that it can use when necessary.

The answer to all these questions is simple and elegant: You perform the actions yourself. The AI model doesn't directly run any computer program, it asks you to do it and report back. If the user asks the AI agent to make a picture of the kitten, then the AI model is responsible for deciding that this would be a good time to draw a kitten. It orchestrates.
