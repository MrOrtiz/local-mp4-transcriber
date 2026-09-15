$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$fixtureFolder = Join-Path $projectRoot 'tmp/fixtures/media'
New-Item -ItemType Directory -Force -Path $fixtureFolder | Out-Null
Add-Type -AssemblyName System.Speech
$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speech.SetOutputToWaveFile((Join-Path $fixtureFolder 'lesson.wav'))
    $speech.Speak('Welcome to this course on local transcription. Today we will learn how to organize audio recordings and extract readable text from documents. Keep the original files unchanged. Each lesson should include its source filename and useful references. Always review technical terms against the recording.')
} finally { $speech.Dispose() }
