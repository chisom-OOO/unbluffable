# Synthetic speech only; no microphone or tester data. Run from the repo root.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$samplePath = Join-Path $PSScriptRoot 'sample.wav'
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $speaker.SetOutputToWaveFile($samplePath, $format)
    $speaker.Speak('The detector catches ninety percent of fraud. So the probability is two over thirteen.')
    $speaker.SetOutputToNull()
    Write-Output "Synthetic 16 kHz mono PCM WAV: $samplePath"
}
finally {
    $speaker.Dispose()
}
