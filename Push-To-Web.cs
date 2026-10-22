using System;
using System.Diagnostics;
using System.IO;
using System.Text;

class Program
{
    static int RunProcess(string filename, string args, string workingDir, out string output)
    {
        var psi = new ProcessStartInfo
        {
            FileName = filename,
            Arguments = args,
            WorkingDirectory = workingDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };

        using (var process = Process.Start(psi))
        {
            var sb = new StringBuilder();
            sb.Append(process.StandardOutput.ReadToEnd());
            sb.Append(process.StandardError.ReadToEnd());
            process.WaitForExit();
            output = sb.ToString();
            return process.ExitCode;
        }
    }

    static void Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.Title = "Hermes Token Dashboard - Push to WWW";

        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("========================================================");
        Console.WriteLine("  Hermes Token Dashboard - ส่งข้อมูลขึ้น WWW (Cloudflare)");
        Console.WriteLine("========================================================");
        Console.ResetColor();
        Console.WriteLine();

        // 1. Determine project directory
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string defaultDir = @"C:\Users\DcF\Documents\token-dashboard";

        string projectDir = baseDir;
        if (!File.Exists(Path.Combine(projectDir, "export_data.py")))
        {
            if (File.Exists(Path.Combine(defaultDir, "export_data.py")))
            {
                projectDir = defaultDir;
            }
            else
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("[ERROR] ไม่พบไฟล์ export_data.py ในโฟลเดอร์โปรเจกต์");
                Console.ResetColor();
                Console.WriteLine("\nกดปุ่มใดๆ เพื่อออก...");
                Console.ReadKey();
                return;
            }
        }

        // 2. Export SQLite to JSON
        Console.ForegroundColor = ConsoleColor.Yellow;
        Console.WriteLine("[1/3] กำลังอ่านข้อมูล Token จาก Hermes SQLite...");
        Console.ResetColor();

        string outExport;
        int code = RunProcess("python", "export_data.py", projectDir, out outExport);
        if (code != 0)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("[ERROR] ไม่สามารถอ่านข้อมูลได้:\n" + outExport);
            Console.ResetColor();
            Console.WriteLine("\nกดปุ่มใดๆ เพื่อออก...");
            Console.ReadKey();
            return;
        }
        Console.ForegroundColor = ConsoleColor.Green;
        Console.WriteLine("  ✓ บันทึกข้อมูล JSON และหน้าเว็บสำเร็จ");
        Console.ResetColor();

        // 3. Git Add & Commit
        Console.ForegroundColor = ConsoleColor.Yellow;
        Console.WriteLine("\n[2/3] กำลังบันทึกการเปลี่ยนแปลง (Git Commit)...");
        Console.ResetColor();

        string outGit;
        RunProcess("git", "add data.json data_day.json data_hour.json index.html static/", projectDir, out outGit);

        string timeStr = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
        int commitCode = RunProcess("git", "commit -m \"Update token usage data [" + timeStr + "]\"", projectDir, out outGit);
        if (commitCode != 0 && outGit.Contains("nothing to commit"))
        {
            Console.WriteLine("  • ข้อมูลล่าสุดตรงกับบนเว็บอยู่แล้ว ไม่มีการเปลี่ยนแปลงใหม่");
        }
        else
        {
            Console.ForegroundColor = ConsoleColor.Green;
            Console.WriteLine("  ✓ Commit ข้อมูลใหม่สำเร็จ (" + timeStr + ")");
            Console.ResetColor();
        }

        // 4. Git Push
        Console.ForegroundColor = ConsoleColor.Yellow;
        Console.WriteLine("\n[3/3] กำลังส่งข้อมูลขึ้น GitHub / Cloudflare Pages...");
        Console.ResetColor();

        int pushCode = RunProcess("git", "push origin main", projectDir, out outGit);
        if (pushCode != 0)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("[ERROR] ไม่สามารถ Push ข้อมูลขึ้น GitHub ได้:\n" + outGit);
            Console.ResetColor();
            Console.WriteLine("\nกดปุ่มใดๆ เพื่อออก...");
            Console.ReadKey();
            return;
        }

        Console.ForegroundColor = ConsoleColor.Green;
        Console.WriteLine("  ✓ Push ขึ้น GitHub สำเร็จเรียบร้อย!");
        Console.ResetColor();

        Console.WriteLine();
        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("========================================================");
        Console.ForegroundColor = ConsoleColor.Green;
        Console.WriteLine("  🎉 ส่งข้อมูลขึ้น WWW เรียบร้อยแล้ว!");
        Console.WriteLine("  🌐 Cloudflare Pages จะอัปเดตหน้าเว็บให้อัตโนมัติทันที");
        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("========================================================");
        Console.ResetColor();

        Console.WriteLine("\nกดปุ่มใดๆ เพื่อปิดหน้าต่างนี้...");
        Console.ReadKey();
    }
}
