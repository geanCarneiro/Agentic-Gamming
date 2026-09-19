using NAudio.CoreAudioApi;

namespace AgenticGaming.HostBridge;

public sealed record AudioDeviceInfo(
    string Id,
    string FriendlyName,
    string State,
    int? SampleRate,
    int? Channels);

public static class AudioDeviceCatalog
{
    public static IReadOnlyList<AudioDeviceInfo> ListRenderDevices()
    {
        using var enumerator = new MMDeviceEnumerator();
        return enumerator
            .EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active)
            .Select(ToInfo)
            .ToArray();
    }

    public static MMDevice? FindRenderDevice(string deviceId)
    {
        using var enumerator = new MMDeviceEnumerator();
        var device = enumerator
            .EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active)
            .FirstOrDefault(candidate => candidate.ID.Equals(deviceId, StringComparison.OrdinalIgnoreCase));

        if (device is null)
        {
            return null;
        }

        // The returned device must remain alive while the recorder is being built.
        return device;
    }

    private static AudioDeviceInfo ToInfo(MMDevice device)
    {
        using var audioClient = device.CreateAudioClient();
        var format = audioClient.MixFormat;
        return new AudioDeviceInfo(
            device.ID,
            device.FriendlyName,
            device.State.ToString(),
            format.SampleRate,
            format.Channels);
    }
}
