import { NextRequest } from "next/server";
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";

export const maxDuration = 300; // 5 mins
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  if (!username || !password) {
    return new Response(JSON.stringify({ error: "Missing credentials" }), {
      status: 400,
    });
  }

  const stream = new TransformStream();
  const writer = stream.writable.getWriter();
  const textEncoder = new TextEncoder();

  let isClosed = false;

  const log = async (msg: string) => {
    console.log(msg);
    if (isClosed) return;
    await writer.write(textEncoder.encode(`data: ${JSON.stringify({ type: "log", msg })}\n\n`));
  };
  
  const end = async () => {
    if (isClosed) return;
    isClosed = true;
    await writer.write(textEncoder.encode(`data: ${JSON.stringify({ type: "end" })}\n\n`));
    await writer.close();
  };

  const notifyError = async (msg: string) => {
    console.error(msg);
    if (isClosed) return;
    await writer.write(textEncoder.encode(`data: ${JSON.stringify({ type: "error", msg })}\n\n`));
    await end();
  };

  (async () => {
    let browser;
    try {
      await log("Initializing Chromium...");
      const executablePath = await chromium.executablePath();
      
      browser = await puppeteer.launch({
        args: [...chromium.args, "--disable-blink-features=AutomationControlled"],
        defaultViewport: { width: 1920, height: 1080 },
        executablePath: executablePath || (process.platform === "win32" ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" : (process.platform === "darwin" ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : "/usr/bin/google-chrome")),
        headless: true,
      });

      const page = await browser.newPage();
      await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36");
      page.setDefaultTimeout(30000);
      page.setDefaultNavigationTimeout(30000);

      await log("Opening LMS login page...");
      await page.goto("https://lms.ssn.edu.in", { waitUntil: "networkidle2" }).catch(() => null);

      await log("Locating and filling credentials...");
      
      await page.waitForSelector('input[name="username"], input[placeholder*="Registration"]', { timeout: 10000 });
      
      const userInput = await page.$('input[name="username"]');
      const passInput = await page.$('input[name="password"]');
      
      let loginBtn = await page.$('button[type="submit"]');
      if (!loginBtn) {
        // Fallback to text selector
        const btns = await page.$$('button');
        for (let b of btns) {
          const text = await b.evaluate(el => el.textContent);
          if (text?.includes("Login")) {
            loginBtn = b;
            break;
          }
        }
      }

      if (!userInput || !passInput || !loginBtn) {
        throw new Error("Login inputs not found.");
      }

      await userInput.type(username);
      await passInput.type(password);
      await loginBtn.click();

      await log("Verifying login...");
      
      // Look for Feedback link
      try {
        await page.waitForNavigation({ waitUntil: "networkidle2", timeout: 15000 });
        await log("[SUCCESS] Login verified successfully.");
      } catch (err) {
        // Evaluate if error is shown
        const errorText = await page.evaluate(() => document.body.innerText.includes("Invalid credentials"));
        if (errorText) throw new Error("Invalid credentials provided.");
        await log("[WARNING] Navigation took too long, proceeding anyway...");
      }

      await log("Navigating to Feedback dashboard...");
      await page.goto("https://lms.ssn.edu.in/feedback", { waitUntil: "networkidle2" }).catch(() => null);

      await log("Detecting subjects with pending feedback...");
      const subjectCards = await page.$$('.subject-card, tr.subject-row, h4.subject-name');
      
      const subjectCount = subjectCards.length;
      if (subjectCount === 0) {
        await log("No subjects found. Process complete.");
        await end();
        return;
      }
      
      await log(`Found ${subjectCount} subjects to process.`);

      let totalSubmitted = 0;
      let totalSkipped = 0;

      for (let i = 0; i < subjectCount; i++) {
        await log(`--- Processing Subject ${i + 1}/${subjectCount} ---`);
        
        // Re-fetch subjects
        const cards = await page.$$('.subject-card, tr.subject-row, h4.subject-name');
        if (!cards[i]) continue;
        await cards[i].click();
        
        await new Promise(r => setTimeout(r, 2000));
        
        // Find give feedback buttons by text
        const feedbackBtns = await page.$$eval('button, a', elements => {
          return elements.filter(el => {
             const t = el.textContent || "";
             return t.includes("Give Feedback") || t.includes("Give feedback");
          }).length;
        });

        if (feedbackBtns === 0) {
          await log("No pending feedback for this subject. Skipping...");
          await page.goBack({ waitUntil: 'networkidle0' }).catch(() => null);
          continue;
        }

        await log(`Pending entries found: ${feedbackBtns}`);

        for (let j = 0; j < feedbackBtns; j++) {
           await log(`Processing entry ${j + 1}/${feedbackBtns}...`);
           
           // Re-fetch all give feedback buttons inside evaluate and click the first one via CDP or directly
           const clicked = await page.evaluate(() => {
             const btns = Array.from(document.querySelectorAll('button, a'));
             const giveFeedbackBtn = btns.find(b => {
               const t = b.textContent || "";
               return t.includes("Give Feedback") || t.includes("Give feedback");
             });
             if (giveFeedbackBtn) {
               (giveFeedbackBtn as HTMLElement).click();
               return true;
             }
             return false;
           });

           if (!clicked) break;

           await new Promise(r => setTimeout(r, 1500));
           
           const alreadySubmitted = await page.evaluate(() => document.body.innerText.includes("Feedback Already Submitted") || document.body.innerText.includes("already provided feedback") || document.body.innerText.includes("No classes found"));
           
           if (alreadySubmitted) {
             await log("[SKIPPED] Feedback already submitted or no classes for this date.");
             await page.goBack({ waitUntil: "networkidle0" }).catch(() => null);
             totalSkipped++;
             continue;
           }

           const submitBtnClicked = await page.evaluate(() => {
             const btns = Array.from(document.querySelectorAll('button'));
             const sBtn = btns.find(b => {
               const t = b.textContent || "";
               return t.includes("Submit") || b.type === "submit";
             });
             if (sBtn) {
               sBtn.click();
               return true;
             }
             return false;
           });

           if (submitBtnClicked) {
             await new Promise(r => setTimeout(r, 2000));
             await log("[SUCCESS] Feedback submitted.");
             totalSubmitted++;
           } else {
             await log("[WARNING] Submit button not found on form.");
             await page.goBack().catch(() => null);
             totalSkipped++;
           }
        }
        
        await page.goto("https://lms.ssn.edu.in/feedback", { waitUntil: "networkidle2" }).catch(() => null);
      }

      await log(`✅ Execution complete. Submitted: ${totalSubmitted}, Skipped: ${totalSkipped}`);
      await end();

    } catch (e: any) {
      await notifyError(e.message || String(e));
    } finally {
      if (browser) {
        await log("Cleaning up browser context...");
        await browser.close().catch(() => null);
      }
    }
  })();

  return new Response(stream.readable, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
}
